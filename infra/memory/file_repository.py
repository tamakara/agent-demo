"""文件系统记忆仓储实现。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal, cast

import aiofiles

from app.errors import NotFoundError, ValidationError
from app.id_codec import normalize_employee_id
from app.interfaces import IMemoryRepository

from .storage_layout import (
    ASSET_PLACEHOLDER_FILE,
    COMPRESSED_MEMORY_FILE,
    EMPLOYEE_ONE,
    PERSONA_FILE,
    SCHEDULE_FILE,
    WORKBOOK_FILE,
    resolve_memory_path,
    resolve_memory_relative_path,
    user_brand_library_dir,
    user_employee_dir,
    user_employee_member_dir,
    user_employee_memory_dir,
    user_employee_memory_file,
    user_employee_notebook_dir,
    user_employee_skills_dir,
    user_employee_workspace_dir,
    user_root_dir,
    user_skill_library_dir,
)


WriteMode = Literal["append", "overwrite"]
AccessMode = Literal["read", "write", "delete"]
AccessScope = Literal["employee", "user"]


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
    SCHEDULE_FILE: (
        "# 日程表\n\n"
        "- 记录任务日程、提醒事项与时间安排。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    WORKBOOK_FILE: (
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
    SCHEDULE_FILE,
    WORKBOOK_FILE,
    ASSET_PLACEHOLDER_FILE,
]
VISIBLE_ROOT_DIRS = ("brand_library", "employee", "skill_library")


class FileMemoryRepository(IMemoryRepository):
    """基于本地文件系统的记忆仓储。"""

    @staticmethod
    def _normalize_tree_path(data_path: str) -> str:
        """规范化目录树路径格式。"""
        normalized = str(data_path or "").strip().replace("\\", "/")
        if not normalized:
            raise ValidationError("data_path 不能为空")
        if normalized.startswith("/"):
            raise ValidationError("data_path 必须是相对路径，不能以 / 开头")
        if normalized in {".", "./"}:
            raise ValidationError("data_path 不能是根目录")
        if ".." in [part for part in normalized.split("/") if part]:
            raise ValidationError("data_path 不能包含 ..")
        return normalized

    @staticmethod
    def _normalize_visible_directory_path(data_path: str) -> str:
        """规范化数字员工可见目录路径，允许使用 ``/`` 表示用户根目录。"""
        normalized = str(data_path or "").strip().replace("\\", "/")
        if not normalized or normalized == "/":
            return "/"
        parts = [part for part in normalized.split("/") if part and part != "."]
        if not parts:
            return "/"
        if ".." in parts:
            raise ValidationError("path 不能包含 ..")
        return "/".join(parts)

    @staticmethod
    def _normalize_single_file_name(file_name: str, *, field_name: str) -> str:
        """规范化单文件名，禁止包含路径。"""
        raw_name = str(file_name or "").strip()
        if not raw_name:
            raise ValidationError(f"{field_name} 不能为空")
        if "/" in raw_name or "\\" in raw_name:
            raise ValidationError(f"{field_name} 必须是文件名，不能包含路径")
        normalized_name = Path(raw_name).name.strip()
        if not normalized_name or normalized_name in {".", ".."}:
            raise ValidationError(f"{field_name} 非法")
        if len(normalized_name) > 255:
            raise ValidationError(f"{field_name} 过长（最多 255 个字符）")
        return normalized_name

    @staticmethod
    def _resolve_safe_path(base_dir: Path, tail_parts: list[str]) -> Path:
        """将 ``tail_parts`` 拼接到 ``base_dir`` 并校验不发生目录逃逸。"""
        target = (base_dir.joinpath(*tail_parts)).resolve()
        if target != base_dir and base_dir not in target.parents:
            raise ValidationError("path 目录非法")
        return target

    @staticmethod
    def _deduplicate_file_name(base_dir: Path, file_name: str) -> str:
        """目标文件名冲突时，生成 ``name(n).ext`` 形式的新文件名。"""
        candidate = Path(file_name)
        stem = candidate.stem
        suffix = candidate.suffix
        index = 1
        renamed = file_name
        while (base_dir / renamed).exists():
            renamed = f"{stem}({index}){suffix}"
            index += 1
        return renamed

    @classmethod
    def _list_directory_entries(cls, *, target_dir: Path, prefix: str, can_write: bool) -> list[dict[str, object]]:
        """列出指定目录下的一层可见条目。"""
        if not target_dir.exists() or not target_dir.is_dir():
            return []
        children = sorted(
            target_dir.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        entries: list[dict[str, object]] = []
        normalized_prefix = str(prefix or "").strip("/")
        for child in children:
            if child.is_dir() and child.name == ".memory":
                continue
            child_path = child.name if not normalized_prefix else f"{normalized_prefix}/{child.name}"
            entries.append(
                {
                    "path": child_path,
                    "is_dir": child.is_dir(),
                    "can_write": can_write,
                }
            )
        return entries

    @staticmethod
    def _ensure_user_root_dirs(user_id: str) -> None:
        """确保用户根目录与公共一级目录存在。"""
        user_root = user_root_dir(user_id)
        employee_root = user_employee_dir(user_id)
        brand_dir = user_brand_library_dir(user_id)
        skill_dir = user_skill_library_dir(user_id)

        user_root.mkdir(parents=True, exist_ok=True)
        for sub_dir in [employee_root, brand_dir, skill_dir]:
            sub_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_user_scaffold(self, user_id: str, employee_id: str) -> None:
        """确保用户目录骨架与指定员工目录存在。"""
        self._ensure_user_root_dirs(user_id)
        employee_dir = user_employee_member_dir(user_id, employee_id)

        scaffold_dirs = [
            employee_dir,
            user_employee_memory_dir(user_id, employee_id),
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

        notebook_dir = user_employee_notebook_dir(user_id, employee_id)
        if not notebook_dir.exists():
            return
        # 仅删除 notebook 目录内的 Markdown 文件（含子目录），
        # 避免误伤 workspace/skills 或其它非记忆文件。
        notebook_root = notebook_dir.resolve()
        for item in notebook_dir.rglob("*.md"):
            if not item.is_file():
                continue
            resolved_item = item.resolve()
            if resolved_item != notebook_root and notebook_root not in resolved_item.parents:
                continue
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

    async def delete_employee_data(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> None:
        """删除指定员工目录下的全部文件与子目录。"""
        self._ensure_user_scaffold(user_id, employee_id)
        employee_root = user_employee_dir(user_id).resolve()
        employee_dir = user_employee_member_dir(user_id, employee_id).resolve()
        if employee_dir == employee_root or employee_root not in employee_dir.parents:
            raise ValidationError("员工目录路径非法")
        if employee_dir.exists():
            shutil.rmtree(employee_dir)

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
            for file_path in notebook_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() == ".md":
                    existing.add(file_path.name)

        existing_sorted = sorted(existing, key=lambda x: x.lower())
        if not existing_sorted:
            return []
        existing_sorted = sorted(set(existing_sorted), key=lambda x: x.lower())
        return self._sort_memory_file_names(existing_sorted)

    @staticmethod
    def _list_employee_ids(employee_root: Path) -> list[str]:
        """扫描并返回用户目录下全部员工编号。"""
        if not employee_root.exists():
            return []
        ids: set[str] = set()
        for child in employee_root.iterdir():
            if not child.is_dir():
                continue
            try:
                ids.add(normalize_employee_id(child.name))
            except ValidationError:
                continue
        return sorted(ids, key=lambda item: int(item))

    def list_employee_data_paths(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> list[dict[str, object]]:
        """列出用户目录三层结构，用于前端用户级文件管理展示。"""
        self._ensure_user_root_dirs(user_id)
        brand_root = user_brand_library_dir(user_id)
        skill_root = user_skill_library_dir(user_id)
        employee_root = user_employee_dir(user_id)
        employee_ids = self._list_employee_ids(employee_root)
        entries: list[dict[str, object]] = []
        seen_paths: set[str] = set()

        def append_entry(path: str, is_dir: bool, *, can_write: bool) -> None:
            """追加目录项并保持去重。"""
            if path in seen_paths:
                return
            seen_paths.add(path)
            entries.append({"path": path, "is_dir": is_dir, "can_write": can_write})

        def append_direct_files(
            base_dir: Path,
            prefix: str,
            *,
            can_write: bool,
            suffixes: set[str] | None = None,
        ) -> None:
            """仅追加目录下一层文件，限制目录深度到三层。"""
            if not base_dir.exists():
                return
            for file_path in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
                if suffixes is not None and file_path.suffix.lower() not in suffixes:
                    continue
                if file_path.is_file():
                    append_entry(f"{prefix}/{file_path.name}", is_dir=False, can_write=can_write)

        append_entry("brand_library", is_dir=True, can_write=True)
        append_direct_files(brand_root, "brand_library", can_write=True)

        append_entry("employee", is_dir=True, can_write=False)
        for member_id in employee_ids:
            # 用户级目录树需要展示全部 employee/{id} 子目录。
            self._ensure_user_scaffold(user_id, member_id)
            member_prefix = f"employee/{member_id}"
            notebook_root = user_employee_notebook_dir(user_id, member_id)
            skills_root = user_employee_skills_dir(user_id, member_id)
            workspace_root = user_employee_workspace_dir(user_id, member_id)
            memory_file = user_employee_memory_file(user_id, member_id)

            append_entry(member_prefix, is_dir=True, can_write=True)
            append_entry(f"{member_prefix}/.memory", is_dir=True, can_write=False)
            if memory_file.exists() and memory_file.is_file():
                append_entry(f"{member_prefix}/.memory/{COMPRESSED_MEMORY_FILE}", is_dir=False, can_write=True)
            append_entry(f"{member_prefix}/notebook", is_dir=True, can_write=True)
            append_direct_files(notebook_root, f"{member_prefix}/notebook", can_write=True)

            append_entry(f"{member_prefix}/skills", is_dir=True, can_write=True)
            append_direct_files(skills_root, f"{member_prefix}/skills", can_write=True)

            append_entry(f"{member_prefix}/workspace", is_dir=True, can_write=True)
            append_direct_files(workspace_root, f"{member_prefix}/workspace", can_write=True)

        append_entry("skill_library", is_dir=True, can_write=True)
        append_direct_files(skill_root, "skill_library", can_write=True)
        return entries

    def employee_data_root(self, user_id: str, employee_id: str = EMPLOYEE_ONE) -> str:
        """返回用户数据目录根（相对路径）。"""
        self._ensure_user_root_dirs(user_id)
        return "."

    @staticmethod
    def _assert_employee_directory_access(
        *,
        actor_employee_id: str,
        target_employee_id: str,
        access_mode: AccessMode,
        access_scope: AccessScope,
    ) -> None:
        """校验员工目录访问权限：本员工可写，其他员工只读。"""
        if access_mode == "read":
            return
        if access_scope == "user":
            return
        if actor_employee_id != target_employee_id:
            raise ValidationError("仅允许修改当前员工目录；其他员工目录仅支持查看")

    def resolve_data_file_path(
        self,
        user_id: str,
        data_path: str = "",
        *,
        employee_id: str = EMPLOYEE_ONE,
        access_mode: AccessMode = "read",
        access_scope: AccessScope = "employee",
    ) -> str:
        """将目录树路径解析为真实绝对文件路径。"""
        if access_scope not in {"employee", "user"}:
            raise ValidationError("access_scope 仅支持 'employee' 或 'user'")
        if access_scope == "employee":
            resolved_actor_employee_id = normalize_employee_id(employee_id)
            self._ensure_user_scaffold(user_id, resolved_actor_employee_id)
        else:
            # 用户级存储管理不依赖当前选中员工，仅确保用户根目录存在。
            resolved_actor_employee_id = EMPLOYEE_ONE
            self._ensure_user_root_dirs(user_id)
        normalized_tree_path = self._normalize_tree_path(data_path)
        path_parts = [part for part in normalized_tree_path.split("/") if part]
        if not path_parts:
            raise ValidationError("data_path 非法")

        root_name = path_parts[0]
        tail_parts = path_parts[1:]
        if root_name == "employee":
            if len(path_parts) < 3:
                raise ValidationError("employee 数据路径必须形如 employee/{employee_id}/<file>")
            resolved_employee_id = normalize_employee_id(path_parts[1])
            tail_parts = path_parts[2:]
            if tail_parts and tail_parts[0] == ".memory" and tail_parts != [".memory", COMPRESSED_MEMORY_FILE]:
                raise ValidationError("员工目录仅允许访问 .memory/memory.md")
            self._assert_employee_directory_access(
                actor_employee_id=resolved_actor_employee_id,
                target_employee_id=resolved_employee_id,
                access_mode=access_mode,
                access_scope=access_scope,
            )
            self._ensure_user_scaffold(user_id, resolved_employee_id)
            base_dir = user_employee_member_dir(user_id, resolved_employee_id).resolve()
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

    def list_employee_visible_directory(
        self,
        user_id: str,
        employee_id: str = EMPLOYEE_ONE,
        data_path: str = "/",
    ) -> dict[str, object]:
        """按数字员工权限列出目录：全用户目录可见，仅隐藏 ``.memory`` 目录。"""
        resolved_employee_id = normalize_employee_id(employee_id)
        self._ensure_user_scaffold(user_id, resolved_employee_id)
        normalized_path = self._normalize_visible_directory_path(data_path)
        path_parts = [part for part in normalized_path.split("/") if part]

        if not path_parts:
            return {
                "path": "/",
                "entries": [
                    {"path": "brand_library", "is_dir": True, "can_write": False},
                    {"path": "employee", "is_dir": True, "can_write": False},
                    {"path": "skill_library", "is_dir": True, "can_write": False},
                ],
            }

        root_name = path_parts[0]
        if root_name not in VISIBLE_ROOT_DIRS:
            raise ValidationError(f"不支持的目录：/{root_name}")

        if root_name in {"brand_library", "skill_library"}:
            if root_name == "brand_library":
                base_dir = user_brand_library_dir(user_id).resolve()
            else:
                base_dir = user_skill_library_dir(user_id).resolve()
            target_dir = self._resolve_safe_path(base_dir, path_parts[1:])
            if not target_dir.exists() or not target_dir.is_dir():
                raise NotFoundError(f"目录不存在：{normalized_path}")
            entries = self._list_directory_entries(
                target_dir=target_dir,
                prefix=normalized_path,
                can_write=False,
            )
            return {"path": normalized_path, "entries": entries}

        if len(path_parts) == 1:
            employee_root = user_employee_dir(user_id).resolve()
            employee_ids = self._list_employee_ids(employee_root)
            return {
                "path": "employee",
                "entries": [
                    {
                        "path": f"employee/{member_id}",
                        "is_dir": True,
                        "can_write": member_id == resolved_employee_id,
                    }
                    for member_id in employee_ids
                ],
            }

        target_employee_id = normalize_employee_id(path_parts[1])
        target_employee_root = user_employee_member_dir(user_id, target_employee_id).resolve()
        if not target_employee_root.exists() or not target_employee_root.is_dir():
            raise NotFoundError(f"目录不存在：{normalized_path}")
        is_owner = target_employee_id == resolved_employee_id

        if len(path_parts) == 2:
            entries = self._list_directory_entries(
                target_dir=target_employee_root,
                prefix=f"employee/{target_employee_id}",
                can_write=is_owner,
            )
            return {"path": f"employee/{target_employee_id}", "entries": entries}

        if ".memory" in path_parts[2:]:
            raise NotFoundError(f"目录不存在：{normalized_path}")

        target_dir = self._resolve_safe_path(target_employee_root, path_parts[2:])
        if not target_dir.exists() or not target_dir.is_dir():
            raise NotFoundError(f"目录不存在：{normalized_path}")
        entries = self._list_directory_entries(
            target_dir=target_dir,
            prefix=normalized_path,
            can_write=is_owner,
        )
        return {"path": normalized_path, "entries": entries}

    def copy_library_file_to_workspace(
        self,
        user_id: str,
        employee_id: str = EMPLOYEE_ONE,
        source_path: str = "",
        *,
        workspace_file_name: str = "",
    ) -> dict[str, object]:
        """复制 brand_library/skill_library 文件到当前员工 workspace。"""
        resolved_employee_id = normalize_employee_id(employee_id)
        self._ensure_user_scaffold(user_id, resolved_employee_id)
        normalized_source_path = self._normalize_visible_directory_path(source_path)
        if normalized_source_path == "/":
            raise ValidationError("source_path 必须指向文件")
        path_parts = [part for part in normalized_source_path.split("/") if part]
        if len(path_parts) < 2:
            raise ValidationError("source_path 必须形如 brand_library/<file> 或 skill_library/<file>")

        source_root_name = path_parts[0]
        if source_root_name == "brand_library":
            source_root = user_brand_library_dir(user_id).resolve()
        elif source_root_name == "skill_library":
            source_root = user_skill_library_dir(user_id).resolve()
        else:
            raise ValidationError("source_path 仅支持 brand_library 或 skill_library")

        source_file = self._resolve_safe_path(source_root, path_parts[1:])
        if not source_file.exists() or not source_file.is_file():
            raise NotFoundError(f"文件不存在：{normalized_source_path}")

        workspace_root = user_employee_workspace_dir(user_id, resolved_employee_id).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)
        requested_workspace_name = str(workspace_file_name or "").strip()
        if requested_workspace_name:
            normalized_workspace_name = self._normalize_single_file_name(
                requested_workspace_name,
                field_name="workspace_file_name",
            )
        else:
            normalized_workspace_name = source_file.name

        target_name = normalized_workspace_name
        target_file = self._resolve_safe_path(workspace_root, [target_name])
        if target_file.exists():
            target_name = self._deduplicate_file_name(workspace_root, target_name)
            target_file = self._resolve_safe_path(workspace_root, [target_name])
        shutil.copy2(source_file, target_file)

        return {
            "source_path": normalized_source_path,
            "source_root": source_root_name,
            "workspace_file_name": target_name,
            "workspace_relative_path": f"employee/{resolved_employee_id}/workspace/{target_name}",
            "renamed": target_name != normalized_workspace_name,
        }

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
    ) -> str:
        """向指定记忆文件写入内容。"""
        self._ensure_user_scaffold(user_id, employee_id)
        normalized_name = file_name.strip()
        path = resolve_memory_path(user_id=user_id, employee_id=employee_id, file_name=normalized_name)
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
