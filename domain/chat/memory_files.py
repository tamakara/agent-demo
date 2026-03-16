"""聊天记忆文件命名与映射规则。"""

from __future__ import annotations

from pathlib import Path


ASSET_PLACEHOLDER_FILE = "file.md"
PERSONA_FILE = "soul.md"
SCHEDULE_FILE = "schedule.md"
WORKBOOK_FILE = "workbook.md"
COMPRESSED_MEMORY_FILE = ".memory.md"


def is_hidden_memory_file_name(file_name: str) -> bool:
    """判断记忆文件名是否为点开头的隐藏文件。"""
    normalized = str(file_name or "").strip()
    return bool(normalized) and normalized.startswith(".")

# 已知文件名固定映射到 employee/{id} 指定位置；未知 .md 默认落到 notebook/。
MEMORY_FILE_LOCATIONS_UNDER_EMPLOYEE: dict[str, Path] = {
    COMPRESSED_MEMORY_FILE: Path(COMPRESSED_MEMORY_FILE),
    ASSET_PLACEHOLDER_FILE: Path("notebook") / ASSET_PLACEHOLDER_FILE,
    SCHEDULE_FILE: Path("notebook") / SCHEDULE_FILE,
    PERSONA_FILE: Path("notebook") / PERSONA_FILE,
    WORKBOOK_FILE: Path("notebook") / WORKBOOK_FILE,
}
