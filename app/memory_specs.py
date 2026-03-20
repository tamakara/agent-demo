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
DEFAULT_MEMORY_CAPACITY_RATIO = 0.10
DEFAULT_NOTEBOOK_CAPACITY_RATIO = 0.04
DEFAULT_DIALOGUE_SUMMARY_RATIO = 0.05
MIN_RATIO = 0.01
MAX_RATIO = 1.0


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
        token_limit_ratio=DEFAULT_MEMORY_CAPACITY_RATIO,
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
SYSTEM_PROMPT_LIMIT_RATIO = round(
    SYSTEM_PROMPT_FIXED_RATIO
    + DEFAULT_MEMORY_CAPACITY_RATIO
    + DEFAULT_NOTEBOOK_CAPACITY_RATIO
    + DEFAULT_DIALOGUE_SUMMARY_RATIO,
    4,
)

MEMORY_FILE_LOCATIONS_UNDER_EMPLOYEE: dict[str, Path] = {
    item.file_name: item.relative_path for item in MANAGED_MEMORY_FILE_SPECS
}


def managed_memory_file_spec(file_name: str) -> ManagedMemoryFileSpec | None:
    normalized = str(file_name or "").strip()
    if not normalized:
        return None
    return MANAGED_MEMORY_FILE_SPECS_BY_NAME.get(normalized)


def normalize_ratio(raw_ratio: float | int | str | None, *, fallback: float) -> float:
    try:
        parsed = float(raw_ratio) if raw_ratio is not None else float(fallback)
    except Exception:  # noqa: BLE001
        parsed = float(fallback)
    if parsed < MIN_RATIO:
        return MIN_RATIO
    if parsed > MAX_RATIO:
        return MAX_RATIO
    return parsed


def system_prompt_limit_ratio(
    memory_capacity_ratio: float | int | str | None = None,
    notebook_capacity_ratio: float | int | str | None = None,
    dialogue_summary_ratio: float | int | str | None = None,
) -> float:
    normalized_memory_capacity_ratio = normalize_ratio(
        memory_capacity_ratio,
        fallback=DEFAULT_MEMORY_CAPACITY_RATIO,
    )
    normalized_notebook_capacity_ratio = normalize_ratio(
        notebook_capacity_ratio,
        fallback=DEFAULT_NOTEBOOK_CAPACITY_RATIO,
    )
    normalized_dialogue_summary_ratio = normalize_ratio(
        dialogue_summary_ratio,
        fallback=DEFAULT_DIALOGUE_SUMMARY_RATIO,
    )
    return round(
        SYSTEM_PROMPT_FIXED_RATIO
        + normalized_memory_capacity_ratio
        + normalized_notebook_capacity_ratio
        + normalized_dialogue_summary_ratio,
        4,
    )


def managed_memory_token_limits(
    total_token_limit: int,
    memory_capacity_ratio: float | int | str | None = None,
    notebook_capacity_ratio: float | int | str | None = None,
) -> dict[str, int]:
    normalized_total = max(1, int(total_token_limit))
    normalized_memory_capacity_ratio = normalize_ratio(
        memory_capacity_ratio,
        fallback=DEFAULT_MEMORY_CAPACITY_RATIO,
    )
    normalized_notebook_capacity_ratio = normalize_ratio(
        notebook_capacity_ratio,
        fallback=DEFAULT_NOTEBOOK_CAPACITY_RATIO,
    )
    notebook_specs = [item for item in MANAGED_MEMORY_FILE_SPECS if item.file_name != COMPRESSED_MEMORY_FILE]
    notebook_file_count = max(1, len(notebook_specs))
    notebook_per_file_ratio = normalized_notebook_capacity_ratio / notebook_file_count
    result: dict[str, int] = {}
    for spec in MANAGED_MEMORY_FILE_SPECS:
        if spec.enforce_token_limit:
            ratio = spec.token_limit_ratio
            if spec.file_name == COMPRESSED_MEMORY_FILE:
                ratio = normalized_memory_capacity_ratio
            else:
                ratio = notebook_per_file_ratio
            result[spec.file_name] = max(1, int(normalized_total * ratio))
    return result


def memory_file_token_limit(
    file_name: str,
    total_token_limit: int,
    memory_capacity_ratio: float | int | str | None = None,
) -> int | None:
    normalized_name = str(file_name or "").strip()
    if not normalized_name:
        return None
    if normalized_name != COMPRESSED_MEMORY_FILE:
        return None
    normalized_total = max(1, int(total_token_limit))
    normalized_memory_capacity_ratio = normalize_ratio(
        memory_capacity_ratio,
        fallback=DEFAULT_MEMORY_CAPACITY_RATIO,
    )
    return max(1, int(normalized_total * normalized_memory_capacity_ratio))


def notebook_total_token_limit(
    total_token_limit: int,
    notebook_capacity_ratio: float | int | str | None = None,
) -> int:
    normalized_total = max(1, int(total_token_limit))
    normalized_notebook_capacity_ratio = normalize_ratio(
        notebook_capacity_ratio,
        fallback=DEFAULT_NOTEBOOK_CAPACITY_RATIO,
    )
    return max(1, int(normalized_total * normalized_notebook_capacity_ratio))


def dialogue_summary_token_limit(
    total_token_limit: int,
    dialogue_summary_ratio: float | int | str | None = None,
) -> int:
    normalized_total = max(1, int(total_token_limit))
    normalized_dialogue_summary_ratio = normalize_ratio(
        dialogue_summary_ratio,
        fallback=DEFAULT_DIALOGUE_SUMMARY_RATIO,
    )
    return max(1, int(normalized_total * normalized_dialogue_summary_ratio))
