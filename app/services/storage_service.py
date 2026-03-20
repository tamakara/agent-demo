"""文件与资源管理应用服务。

该服务位于 app 层，负责把“面向业务”的存储操作封装出来：
- 员工记忆文件初始化/重置/删除
- 用户目录树、文本文件读写删
- 上传文件名规范化与重名去重

关键原则：
- 服务仅依赖 IMemoryRepository 抽象，不依赖具体文件系统实现。
- 对外暴露业务语义方法，屏蔽 infra 层路径细节。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.errors import NotFoundError, ValidationError
from app.interfaces import IMemoryRepository
from domain.models import MemoryFileEntry


# 可编辑文本后缀白名单。
EDITABLE_TEXT_SUFFIXES = {".md", ".txt"}
# 允许删除文件的根目录白名单，避免误删关键运行目录。
DELETABLE_DATA_ROOTS = {"brand_library", "skill_library"}
# 识别 `name(1)` / `name（1）` 这种已带序号的文件名。
DUPLICATE_NAME_SUFFIX_PATTERN = re.compile(r"^(?P<base>.*?)(?:\((?P<idx>\d+)\)|（(?P<idx_cn>\d+)）)$")


class StorageService:
    """存储相关应用服务。"""

    def __init__(self, memory_repo: IMemoryRepository) -> None:
        self.memory_repo = memory_repo

    async def ensure_employee_files(self, user_id: str, employee_id: str) -> None:
        """确保员工目录下的记忆文件骨架存在。"""
        await self.memory_repo.ensure_memory_files_exist(user_id, employee_id)

    async def list_employee_files(self, user_id: str, employee_id: str) -> list[MemoryFileEntry]:
        """读取员工可管理记忆文件列表。

        策略：
        - 逐个读取文件内容；某个文件读取失败不会中断整体列表返回。
        """
        files: list[MemoryFileEntry] = []
        for file_name in self.memory_repo.list_memory_file_names(user_id, employee_id):
            try:
                content = await self.memory_repo.read_memory_file(
                    user_id=user_id,
                    employee_id=employee_id,
                    file_name=file_name,
                )
            except Exception:  # noqa: BLE001
                # 单文件失败兜底为空，避免页面整体不可用。
                content = ""
            files.append(
                MemoryFileEntry(
                    file_name=file_name,
                    relative_path=self.memory_repo.memory_relative_path(file_name),
                    content=content,
                )
            )
        return files

    async def reset_employee_memory(self, user_id: str, employee_id: str) -> tuple[list[str], list[MemoryFileEntry]]:
        """重置员工记忆文件并返回最新文件列表。"""
        restored = await self.memory_repo.reset_memory_to_initial_content(user_id, employee_id)
        files = await self.list_employee_files(user_id, employee_id)
        return restored, files

    async def delete_employee_data(self, user_id: str, employee_id: str) -> None:
        """删除指定员工目录数据。"""
        await self.memory_repo.delete_employee_data(user_id, employee_id)

    def list_data_paths(self, user_id: str) -> list[dict[str, object]]:
        """列出用户目录树（用于前端文件管理）。"""
        return self.memory_repo.list_employee_data_paths(user_id)

    def data_root(self, user_id: str) -> str:
        """返回用户数据根路径的对外表示。"""
        return self.memory_repo.employee_data_root(user_id)

    def resolve_data_file_path(
        self,
        user_id: str,
        data_path: str,
        *,
        employee_id: str = "1",
        access_mode: str = "read",
        access_scope: str = "employee",
    ) -> str:
        """把目录树路径解析为本地绝对路径（含权限校验）。"""
        return self.memory_repo.resolve_data_file_path(
            user_id,
            data_path,
            employee_id=employee_id,
            access_mode=access_mode,
            access_scope=access_scope,
        )

    @staticmethod
    def data_root_from_tree_path(path: str) -> str:
        """提取目录树路径的一级目录名。"""
        parts = [part for part in str(path or "").strip().split("/") if part]
        return parts[0] if parts else ""

    @staticmethod
    def normalize_upload_file_name(file_name: str) -> str:
        """规范化上传文件名，禁止路径穿越和非法名。"""
        raw = str(file_name or "").strip()
        if not raw:
            raise ValidationError("上传文件名不能为空")
        name = Path(raw).name.strip()
        if not name or name in {".", ".."}:
            raise ValidationError("上传文件名非法")
        if len(name) > 255:
            raise ValidationError("上传文件名过长（最多 255 个字符）")
        return name

    @staticmethod
    def deduplicate_file_name(base_dir: Path, file_name: str) -> str:
        """处理同名文件冲突，生成下一个可用文件名。"""
        candidate = Path(file_name)
        stem = candidate.stem
        suffix = candidate.suffix

        matched = DUPLICATE_NAME_SUFFIX_PATTERN.fullmatch(stem)
        if matched:
            base_stem = str(matched.group("base") or "").strip()
            index_raw = matched.group("idx") or matched.group("idx_cn") or "0"
            start_index = max(1, int(index_raw) + 1)
            if not base_stem:
                base_stem = stem
                start_index = 1
        else:
            base_stem = stem
            start_index = 1

        index = start_index
        while True:
            renamed = f"{base_stem}({index}){suffix}"
            target_path = (base_dir / renamed).resolve()
            if not target_path.exists():
                return renamed
            index += 1

    def read_text_file(self, user_id: str, path: str) -> str:
        """读取用户目录中的文本文件内容。"""
        abs_path = self.resolve_data_file_path(
            user_id,
            path,
            access_mode="read",
            access_scope="user",
        )
        file_path = Path(abs_path)
        if file_path.suffix.lower() not in EDITABLE_TEXT_SUFFIXES:
            raise ValidationError(f"仅支持文本文件读取（.md/.txt）：{path}")
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(f"文本文件编码不支持 UTF-8：{path}") from exc

    def write_text_file(self, user_id: str, path: str, content: str, mode: str) -> str:
        """写入用户目录中的文本文件并返回最新内容。"""
        abs_path = self.resolve_data_file_path(
            user_id,
            path,
            access_mode="write",
            access_scope="user",
        )
        file_path = Path(abs_path)
        if file_path.suffix.lower() not in EDITABLE_TEXT_SUFFIXES:
            raise ValidationError(f"仅支持文本文件写入（.md/.txt）：{path}")

        if mode == "append":
            # 追加模式：自动补换行，便于后续继续 append。
            append_text = content
            if append_text and not append_text.endswith("\n"):
                append_text = f"{append_text}\n"
            with file_path.open("a", encoding="utf-8") as output_file:
                output_file.write(append_text)
        elif mode == "overwrite":
            file_path.write_text(content, encoding="utf-8")
        else:
            raise ValidationError("mode 仅支持 append 或 overwrite")

        return file_path.read_text(encoding="utf-8")

    def delete_user_file(self, user_id: str, path: str) -> None:
        """删除用户文件（仅允许白名单根目录）。"""
        root_name = self.data_root_from_tree_path(path)
        if root_name not in DELETABLE_DATA_ROOTS:
            raise ValidationError("仅允许删除 brand_library 与 skill_library 下的文件")
        abs_path = self.resolve_data_file_path(
            user_id,
            path,
            access_mode="delete",
            access_scope="user",
        )
        target = Path(abs_path)
        if not target.exists() or not target.is_file():
            raise NotFoundError(f"文件不存在：{path}")
        target.unlink()

    def list_visible_directory(self, user_id: str, employee_id: str, path: str) -> dict[str, Any]:
        """按员工权限视图列目录。"""
        return self.memory_repo.list_employee_visible_directory(
            user_id=user_id,
            employee_id=employee_id,
            data_path=path,
        )

    def copy_library_file_to_workspace(
        self,
        user_id: str,
        employee_id: str,
        source_path: str,
        *,
        workspace_file_name: str = "",
    ) -> dict[str, Any]:
        """复制素材库文件到员工 workspace。"""
        return self.memory_repo.copy_library_file_to_workspace(
            user_id=user_id,
            employee_id=employee_id,
            source_path=source_path,
            workspace_file_name=workspace_file_name,
        )
