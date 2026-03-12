"""文件系统记忆仓储实现。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import aiofiles

from app.ports.repositories import MemoryFileRepositoryPort
from common.errors import NotFoundError, ValidationError

from .storage_layout import (
    ASSET_PLACEHOLDER_FILE,
    COMPRESSED_MEMORY_FILE,
    EMPLOYEE_ONE,
    NOTEBOOK_SUBDIR,
    PERSONA_FILE,
    SYSTEM_PROMPT_FILE,
    resolve_memory_path,
    resolve_memory_relative_path,
    user_brand_library_dir,
    user_employee_dir,
    user_employee_member_dir,
    user_employee_memory_file,
    user_employee_notebook_dir,
    user_employee_skills_dir,
    user_employee_workspace_dir,
    user_root_dir,
    user_skill_library_dir,
)


WriteMode = Literal["append", "overwrite"]


EMPLOYEE_INITIAL_MEMORY_FILES: dict[str, str] = {
    COMPRESSED_MEMORY_FILE: (
        "# 压缩记忆\n\n"
        "- 记录经过压缩后的关键长期记忆。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    PERSONA_FILE: (
        "# 人格设定\n\n"
        "- **核心定位**：完全服从用户的指令，同时具备高度创新能力的数字员工。\n"
        "- **表达风格**：专业、高效，在执行任务时会主动提供创新性的建议或方案。\n"
        "- **决策风格**：以用户的需求为最高优先级，在框架内寻求最优、最创新的解决路径。\n"
    ),
    "日程表.md": (
        "# 日程表\n\n"
        "- 记录任务日程、提醒事项与时间安排。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    "工作手册.md": (
        "# 工作手册\n\n"
        "- 记录稳定流程、工作规范与执行清单。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    ASSET_PLACEHOLDER_FILE: (
        "# 素材库笔记（占位）\n\n"
        "- 本文件用于占位展示，不作为默认常驻上下文来源。\n"
        "- 除非用户明确要求，否则不应主动读取或写入该文件。\n"
    ),
}

PREFERRED_FILE_ORDER = [
    COMPRESSED_MEMORY_FILE,
    PERSONA_FILE,
    "日程表.md",
    "工作手册.md",
    ASSET_PLACEHOLDER_FILE,
    SYSTEM_PROMPT_FILE,
]
VISIBLE_TEXT_SUFFIXES = {".md"}
VISIBLE_IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp"}


class FileMemoryRepository(MemoryFileRepositoryPort):
    """基于本地文件系统的记忆仓储。"""

    @staticmethod
    def _normalize_tree_path(data_path: str) -> str:
        """规范化目录树路径格式。"""
        normalized = str(data_path or "").strip()
        if not normalized:
            raise ValidationError("data_path 不能为空")
        if not normalized.startswith("/"):
            raise ValidationError("data_path 必须以 / 开头")
        if normalized == "/":
            raise ValidationError("data_path 不能是根目录")
        return normalized

    def _ensure_user_scaffold(self, user_id: str, employee_id: str) -> None:
        """确保用户目录骨架与指定员工目录存在。"""
        user_root = user_root_dir(user_id)
        employee_root = user_employee_dir(user_id)
        brand_dir = user_brand_library_dir(user_id)
        skill_dir = user_skill_library_dir(user_id)
        employee_dir = user_employee_member_dir(user_id, employee_id)

        user_root.mkdir(parents=True, exist_ok=True)

        scaffold_dirs = [
            employee_root,
            brand_dir,
            skill_dir,
            employee_dir,
            user_employee_notebook_dir(user_id, employee_id),
            user_employee_workspace_dir(user_id, employee_id),
            user_employee_skills_dir(user_id, employee_id),
        ]
        for sub_dir in scaffold_dirs:
            sub_dir.mkdir(parents=True, exist_ok=True)

    def _write_initial_memory_files(self, *, user_id: str, employee_id: str, overwrite: bool) -> list[str]:
        """写入初始记忆文件，返回实际写入的文件名列表。"""
        self._ensure_user_scaffold(user_id, employee_id)
        written: list[str] = []
        for file_name, initial_content in EMPLOYEE_INITIAL_MEMORY_FILES.items():
            target = resolve_memory_path(user_id=user_id, employee_id=employee_id, file_name=file_name)
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(initial_content, encoding="utf-8")
            written.append(file_name)
        return written

    def _clear_memory_files(self, *, user_id: str, employee_id: str) -> None:
        """清空 employee/{id} 中的记忆 Markdown 文件，保留 workspace/skills。"""
        self._ensure_user_scaffold(user_id, employee_id)

        memory_file = user_employee_memory_file(user_id, employee_id)
        if memory_file.exists() and memory_file.is_file():
            memory_file.unlink()

        notebook_dirs = [user_employee_notebook_dir(user_id, employee_id)]
        for notebook_dir in notebook_dirs:
            if not notebook_dir.exists():
                continue
            for item in notebook_dir.glob("*.md"):
                if item.is_file():
                    item.unlink()

    async def ensure_memory_files_exist(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> None:
        """确保数字员工记忆文件存在，不覆盖已有内容。"""
        self._ensure_user_scaffold(user_id, employee_id)
        self._write_initial_memory_files(user_id=user_id, employee_id=employee_id, overwrite=False)

    async def reset_memory_to_initial_content(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> list[str]:
        """重置指定员工记忆目录并重新写入初始化文件。"""
        self._ensure_user_scaffold(user_id, employee_id)
        self._clear_memory_files(user_id=user_id, employee_id=employee_id)
        return self._write_initial_memory_files(user_id=user_id, employee_id=employee_id, overwrite=True)

    @staticmethod
    def _sort_memory_file_names(existing: list[str]) -> list[str]:
        """按预设顺序排序文件名，其余文件保持字母序补齐。"""
        existing_set = set(existing)
        ordered = [name for name in PREFERRED_FILE_ORDER if name in existing_set]
        ordered.extend(name for name in existing if name not in ordered)
        return ordered

    def list_memory_file_names(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> list[str]:
        """列出指定数字员工记忆文件名。"""
        self._ensure_user_scaffold(user_id, employee_id)
        existing: set[str] = set()

        memory_file = user_employee_memory_file(user_id, employee_id)
        if memory_file.exists() and memory_file.is_file():
            existing.add(COMPRESSED_MEMORY_FILE)

        notebook_dir = user_employee_notebook_dir(user_id, employee_id)
        if notebook_dir.exists():
            for file_path in notebook_dir.glob("*.md"):
                if file_path.is_file():
                    existing.add(file_path.name)

        existing_sorted = sorted(existing, key=lambda x: x.lower())
        if not existing_sorted:
            return []
        existing_sorted = sorted(set(existing_sorted), key=lambda x: x.lower())
        return self._sort_memory_file_names(existing_sorted)

    def list_employee_data_paths(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> list[dict[str, object]]:
        """列出用户目录三层结构，用于前端目录展示。"""
        self._ensure_user_scaffold(user_id, employee_id)
        brand_root = user_brand_library_dir(user_id)
        skill_root = user_skill_library_dir(user_id)
        notebook_root = user_employee_notebook_dir(user_id, employee_id)
        skills_root = user_employee_skills_dir(user_id, employee_id)
        workspace_root = user_employee_workspace_dir(user_id, employee_id)
        entries: list[dict[str, object]] = []
        seen_paths: set[str] = set()

        def append_entry(path: str, is_dir: bool) -> None:
            """追加目录项并保持去重。"""
            if path in seen_paths:
                return
            seen_paths.add(path)
            entries.append({"path": path, "is_dir": is_dir})

        def append_direct_files(base_dir: Path, prefix: str, *, suffixes: set[str]) -> None:
            """仅追加目录下一层指定后缀文件，限制目录深度到三层。"""
            if not base_dir.exists():
                return
            for file_path in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
                if file_path.suffix.lower() not in suffixes:
                    continue
                if file_path.is_file():
                    append_entry(f"{prefix}/{file_path.name}", is_dir=False)

        append_entry("/brand_library", is_dir=True)
        append_direct_files(
            brand_root,
            "/brand_library",
            suffixes=VISIBLE_TEXT_SUFFIXES | VISIBLE_IMAGE_SUFFIXES,
        )

        append_entry("/employee", is_dir=True)
        append_entry("/employee/memory.md", is_dir=False)

        append_entry("/employee/notebook", is_dir=True)
        append_direct_files(notebook_root, "/employee/notebook", suffixes=VISIBLE_TEXT_SUFFIXES)

        append_entry("/employee/skills", is_dir=True)
        append_direct_files(skills_root, "/employee/skills", suffixes=VISIBLE_TEXT_SUFFIXES)

        append_entry("/employee/workspace", is_dir=True)
        append_direct_files(
            workspace_root,
            "/employee/workspace",
            suffixes=VISIBLE_TEXT_SUFFIXES | VISIBLE_IMAGE_SUFFIXES,
        )

        append_entry("/skill_library", is_dir=True)
        append_direct_files(skill_root, "/skill_library", suffixes=VISIBLE_TEXT_SUFFIXES)
        return entries

    def employee_data_root(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> str:
        """返回用户数据目录绝对路径。"""
        self._ensure_user_scaffold(user_id, employee_id)
        return str(user_root_dir(user_id).resolve())

    def resolve_data_file_path(self, user_id: str, employee_id: str = EMPLOYEE_ONE, data_path: str = "") -> str:
        """将目录树路径解析为真实绝对文件路径。"""
        self._ensure_user_scaffold(user_id, employee_id)
        normalized_tree_path = self._normalize_tree_path(data_path)
        path_parts = [part for part in normalized_tree_path.split("/") if part]
        if not path_parts:
            raise ValidationError("data_path 非法")

        root_name = path_parts[0]
        tail_parts = path_parts[1:]
        if root_name == "employee":
            base_dir = user_employee_member_dir(user_id, employee_id).resolve()
        elif root_name == "brand_library":
            base_dir = user_brand_library_dir(user_id).resolve()
        elif root_name == "skill_library":
            base_dir = user_skill_library_dir(user_id).resolve()
        else:
            raise ValidationError(f"不支持的数据目录：/{root_name}")

        target = (base_dir.joinpath(*tail_parts)).resolve()
        if target != base_dir and base_dir not in target.parents:
            raise ValidationError("data_path 目录非法")
        if not target.exists() or not target.is_file():
            raise NotFoundError(f"文件不存在：{normalized_tree_path}")
        return str(target)

    @staticmethod
    def memory_relative_path(file_name: str) -> str:
        """返回记忆文件相对于员工目录的路径。"""
        return resolve_memory_relative_path(file_name).as_posix()

    async def read_memory_file(self, *, user_id: str, employee_id: str = EMPLOYEE_ONE, file_name: str) -> str:
        """读取指定记忆文件内容。"""
        self._ensure_user_scaffold(user_id, employee_id)
        normalized_name = file_name.strip()
        path = resolve_memory_path(user_id=user_id, employee_id=employee_id, file_name=normalized_name)
        if not path.exists():
            raise NotFoundError(f"记忆文件不存在：{normalized_name}")
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return await f.read()

    async def write_memory_file(
        self,
        *,
        user_id: str,
        employee_id: str = EMPLOYEE_ONE,
        file_name: str,
        content: str,
        mode: str,
        allow_system_prompt: bool = False,
    ) -> str:
        """向指定记忆文件写入内容。"""
        self._ensure_user_scaffold(user_id, employee_id)
        normalized_name = file_name.strip()
        path = resolve_memory_path(user_id=user_id, employee_id=employee_id, file_name=normalized_name)
        if normalized_name == SYSTEM_PROMPT_FILE and not allow_system_prompt:
            raise ValidationError(f"{SYSTEM_PROMPT_FILE} 仅允许通过人工接口更新")
        if mode not in {"append", "overwrite"}:
            raise ValidationError("mode 只能是 'append' 或 'overwrite'")
        if not isinstance(content, str):
            raise ValidationError("content 必须是字符串")

        path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = "a" if mode == "append" else "w"
        typed_mode = cast(WriteMode, mode)
        async with aiofiles.open(path, file_mode, encoding="utf-8") as f:
            await f.write(content)
            # 追加模式下补全换行，便于后续继续 append。
            if typed_mode == "append" and content and not content.endswith("\n"):
                await f.write("\n")
        return f"写入成功：{normalized_name}（模式：{mode}）"
