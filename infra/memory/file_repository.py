"""文件系统记忆仓储实现。"""

from __future__ import annotations

import shutil
from typing import Literal, cast

import aiofiles

from app.ports.repositories import MemoryFileRepositoryPort
from common.errors import NotFoundError, ValidationError

from .storage_layout import (
    ASSET_PLACEHOLDER_FILE,
    SYSTEM_PROMPT_FILE,
    resolve_memory_path,
    user_brand_library_dir,
    user_memory_dir,
    user_root_dir,
    user_skill_library_dir,
)


WriteMode = Literal["append", "overwrite"]


INITIAL_MEMORY_FILES: dict[str, str] = {
    "人格记忆.md": (
        "# 人格记忆\n\n"
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
        "# 素材库记忆（占位）\n\n"
        "- 本文件用于占位展示，不作为默认常驻上下文来源。\n"
        "- 除非用户明确要求，否则不应主动读取或写入该文件。\n"
    ),
    "通用记忆.md": (
        "# 通用记忆\n\n"
        "- 记录无法归类到其他记忆文件的重要信息。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    SYSTEM_PROMPT_FILE: (
        "# 系统提示词\n\n"
        "## 规则\n"
        "你是一个支持长期记忆的对话智能体。请严格遵守：\n"
        "1. 优先根据用户意图回答，避免无关扩写。\n"
        "2. 写入记忆前先判断是否属于长期稳定信息，避免把一次性噪声写入。\n"
        "3. 默认不要主动读取或写入 `素材库记忆.md`（除非用户明确要求）。\n"
        "4. 工具执行失败时先解释原因，再给出可行替代方案。\n"
        "5. 当用户问题依赖当前时间（如“现在几点”“今天是几号”）时，优先调用 `get_current_time`。\n\n"
        "## 工具定义\n"
        "- `read_memory_file(file_name)`：读取指定记忆文件。\n"
        "- `write_memory_file(file_name, content, mode=append|overwrite)`：写入记忆文件。\n"
        "- `get_current_time()`：获取当前 UTC 与本地时间。\n"
    ),
}

PREFERRED_FILE_ORDER = list(INITIAL_MEMORY_FILES.keys())


class FileMemoryRepository(MemoryFileRepositoryPort):
    """基于本地文件系统的记忆仓储。"""

    def _ensure_user_scaffold(self, user_id: str):
        """确保用户目录骨架存在，并返回 memory 目录路径。"""
        user_root = user_root_dir(user_id)
        memory_dir = user_memory_dir(user_id)
        brand_dir = user_brand_library_dir(user_id)
        skill_dir = user_skill_library_dir(user_id)

        user_root.mkdir(parents=True, exist_ok=True)
        for sub_dir in (memory_dir, brand_dir, skill_dir):
            sub_dir.mkdir(parents=True, exist_ok=True)
        return memory_dir

    def _write_initial_memory_files(self, *, user_id: str, overwrite: bool) -> list[str]:
        """写入初始记忆文件，返回实际写入的文件名列表。"""
        user_dir = self._ensure_user_scaffold(user_id)
        written: list[str] = []
        for file_name, initial_content in INITIAL_MEMORY_FILES.items():
            target = user_dir / file_name
            if target.exists() and not overwrite:
                continue
            target.write_text(initial_content, encoding="utf-8")
            written.append(file_name)
        return written

    def _clear_memory_dir(self, *, user_id: str) -> None:
        """清空用户 memory 目录。"""
        user_dir = self._ensure_user_scaffold(user_id)
        if not user_dir.exists():
            return
        for item in user_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    async def ensure_memory_files_exist(self, user_id: str) -> None:
        """确保用户记忆文件存在，不覆盖已有内容。"""
        self._ensure_user_scaffold(user_id)
        self._write_initial_memory_files(user_id=user_id, overwrite=False)

    async def reset_memory_to_initial_content(self, user_id: str) -> list[str]:
        """重置记忆目录并重新写入初始化文件。"""
        self._ensure_user_scaffold(user_id)
        self._clear_memory_dir(user_id=user_id)
        return self._write_initial_memory_files(user_id=user_id, overwrite=True)

    @staticmethod
    def _sort_memory_file_names(existing: list[str]) -> list[str]:
        """按预设顺序排序文件名，其余文件保持字母序补齐。"""
        existing_set = set(existing)
        ordered = [name for name in PREFERRED_FILE_ORDER if name in existing_set]
        ordered.extend(name for name in existing if name not in ordered)
        return ordered

    def list_memory_file_names(self, user_id: str) -> list[str]:
        """列出用户记忆文件名。"""
        user_dir = self._ensure_user_scaffold(user_id)
        existing = sorted(
            [p.name for p in user_dir.glob("*.md") if p.is_file()],
            key=lambda x: x.lower(),
        )
        return self._sort_memory_file_names(existing)

    async def read_memory_file(self, *, user_id: str, file_name: str) -> str:
        """读取指定记忆文件内容。"""
        self._ensure_user_scaffold(user_id)
        path = resolve_memory_path(user_id=user_id, file_name=file_name)
        if not path.exists():
            raise NotFoundError(f"记忆文件不存在：{file_name}")
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return await f.read()

    async def write_memory_file(
        self,
        *,
        user_id: str,
        file_name: str,
        content: str,
        mode: str,
        allow_system_prompt: bool = False,
    ) -> str:
        """向指定记忆文件写入内容。"""
        self._ensure_user_scaffold(user_id)
        path = resolve_memory_path(user_id=user_id, file_name=file_name)
        if file_name == SYSTEM_PROMPT_FILE and not allow_system_prompt:
            raise ValidationError(f"{SYSTEM_PROMPT_FILE} 仅允许通过人工接口更新")
        if mode not in {"append", "overwrite"}:
            raise ValidationError("mode 只能是 'append' 或 'overwrite'")
        if not isinstance(content, str):
            raise ValidationError("content 必须是字符串")

        file_mode = "a" if mode == "append" else "w"
        typed_mode = cast(WriteMode, mode)
        async with aiofiles.open(path, file_mode, encoding="utf-8") as f:
            await f.write(content)
            # 追加模式下补全换行，便于后续继续 append。
            if typed_mode == "append" and content and not content.endswith("\n"):
                await f.write("\n")
        return f"写入成功：{file_name}（模式：{mode}）"

