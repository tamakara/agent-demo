"""Managed memory file specifications and token budgets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ASSET_PLACEHOLDER_FILE = "file.md"
PERSONA_FILE = "soul.md"
SCHEDULE_FILE = "schedule.md"
WORKBOOK_FILE = "workbook.md"
COMPRESSED_MEMORY_DIR = ".memory"
COMPRESSED_MEMORY_FILE = "memory.md"


@dataclass(frozen=True, slots=True)
class ManagedMemoryFileSpec:
    file_name: str
    relative_path: Path
    token_limit_ratio: float
    enforce_token_limit: bool = True


MANAGED_MEMORY_FILE_SPECS: tuple[ManagedMemoryFileSpec, ...] = (
    ManagedMemoryFileSpec(
        file_name=COMPRESSED_MEMORY_FILE,
        relative_path=Path(COMPRESSED_MEMORY_DIR) / COMPRESSED_MEMORY_FILE,
        token_limit_ratio=0.05,
    ),
    ManagedMemoryFileSpec(
        file_name=ASSET_PLACEHOLDER_FILE,
        relative_path=Path("notebook") / ASSET_PLACEHOLDER_FILE,
        token_limit_ratio=0.01,
    ),
    ManagedMemoryFileSpec(
        file_name=SCHEDULE_FILE,
        relative_path=Path("notebook") / SCHEDULE_FILE,
        token_limit_ratio=0.01,
    ),
    ManagedMemoryFileSpec(
        file_name=PERSONA_FILE,
        relative_path=Path("notebook") / PERSONA_FILE,
        token_limit_ratio=0.01,
    ),
    ManagedMemoryFileSpec(
        file_name=WORKBOOK_FILE,
        relative_path=Path("notebook") / WORKBOOK_FILE,
        token_limit_ratio=0.01,
    ),
)

MANAGED_MEMORY_FILE_SPECS_BY_NAME: dict[str, ManagedMemoryFileSpec] = {
    item.file_name: item for item in MANAGED_MEMORY_FILE_SPECS
}

SYSTEM_PROMPT_FIXED_RATIO = 0.01
MANAGED_MEMORY_FILES_RATIO = sum(item.token_limit_ratio for item in MANAGED_MEMORY_FILE_SPECS)
SYSTEM_PROMPT_LIMIT_RATIO = round(SYSTEM_PROMPT_FIXED_RATIO + MANAGED_MEMORY_FILES_RATIO, 4)

MEMORY_FILE_LOCATIONS_UNDER_EMPLOYEE: dict[str, Path] = {
    item.file_name: item.relative_path for item in MANAGED_MEMORY_FILE_SPECS
}


def managed_memory_file_spec(file_name: str) -> ManagedMemoryFileSpec | None:
    normalized = str(file_name or "").strip()
    if not normalized:
        return None
    return MANAGED_MEMORY_FILE_SPECS_BY_NAME.get(normalized)


def managed_memory_token_limits(total_token_limit: int) -> dict[str, int]:
    normalized_total = max(1, int(total_token_limit))
    result: dict[str, int] = {}
    for spec in MANAGED_MEMORY_FILE_SPECS:
        if spec.enforce_token_limit:
            result[spec.file_name] = max(1, int(normalized_total * spec.token_limit_ratio))
    return result


def memory_file_token_limit(file_name: str, total_token_limit: int) -> int | None:
    normalized_name = str(file_name or "").strip()
    if not normalized_name:
        return None
    return managed_memory_token_limits(total_token_limit).get(normalized_name)
