"""Window budget policy used by application services."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory_specs import (
    DEFAULT_DIALOGUE_SUMMARY_RATIO,
    DEFAULT_MEMORY_CAPACITY_RATIO,
    DEFAULT_NOTEBOOK_CAPACITY_RATIO,
    dialogue_summary_token_limit,
    notebook_total_token_limit,
    normalize_ratio,
    system_prompt_limit_ratio,
)


DEFAULT_TOTAL_LIMIT = 200_000
MIN_TOTAL_LIMIT = 20_000
DEFAULT_RETENTION_RATIO = 0.10


@dataclass(slots=True, frozen=True)
class WindowThresholds:
    total_limit: int
    system_prompt_limit: int
    retention_limit: int
    resident_limit: int
    dialogue_limit: int
    buffer_limit: int
    memory_token_limit: int
    summary_token_limit: int
    notebook_total_token_limit: int
    compression_trigger: int
    memory_capacity_ratio: float
    notebook_capacity_ratio: float
    dialogue_summary_ratio: float
    retention_ratio: float

    @classmethod
    def from_total_limit(
        cls,
        total_limit: int,
        *,
        memory_capacity_ratio: float | int | str | None = DEFAULT_MEMORY_CAPACITY_RATIO,
        notebook_capacity_ratio: float | int | str | None = DEFAULT_NOTEBOOK_CAPACITY_RATIO,
        dialogue_summary_ratio: float | int | str | None = DEFAULT_DIALOGUE_SUMMARY_RATIO,
        retention_ratio: float | int | str | None = DEFAULT_RETENTION_RATIO,
    ) -> "WindowThresholds":
        normalized = max(MIN_TOTAL_LIMIT, int(total_limit))
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
        normalized_retention_ratio = normalize_ratio(
            retention_ratio,
            fallback=DEFAULT_RETENTION_RATIO,
        )

        system_ratio = system_prompt_limit_ratio(
            normalized_memory_capacity_ratio,
            normalized_notebook_capacity_ratio,
            normalized_dialogue_summary_ratio,
        )
        system_prompt_limit = max(1, int(normalized * system_ratio))
        memory_token_limit = max(1, int(normalized * normalized_memory_capacity_ratio))
        summary_limit = dialogue_summary_token_limit(
            normalized,
            dialogue_summary_ratio=normalized_dialogue_summary_ratio,
        )
        notebook_limit = notebook_total_token_limit(
            normalized,
            notebook_capacity_ratio=normalized_notebook_capacity_ratio,
        )
        retention_limit = max(1, int(normalized * normalized_retention_ratio))
        resident_limit = system_prompt_limit + retention_limit

        max_resident = max(1, normalized - 1)
        if resident_limit > max_resident:
            overflow = resident_limit - max_resident
            shrink_retention = min(max(0, retention_limit - 1), overflow)
            retention_limit -= shrink_retention
            resident_limit -= shrink_retention
            overflow = resident_limit - max_resident
            if overflow > 0:
                shrink_system = min(max(0, system_prompt_limit - 1), overflow)
                system_prompt_limit -= shrink_system
                resident_limit -= shrink_system

        dialogue_limit = max(1, normalized - resident_limit)
        buffer_limit = dialogue_limit
        return cls(
            total_limit=normalized,
            system_prompt_limit=system_prompt_limit,
            retention_limit=retention_limit,
            resident_limit=resident_limit,
            dialogue_limit=dialogue_limit,
            buffer_limit=buffer_limit,
            memory_token_limit=memory_token_limit,
            summary_token_limit=summary_limit,
            notebook_total_token_limit=notebook_limit,
            compression_trigger=normalized,
            memory_capacity_ratio=normalized_memory_capacity_ratio,
            notebook_capacity_ratio=normalized_notebook_capacity_ratio,
            dialogue_summary_ratio=normalized_dialogue_summary_ratio,
            retention_ratio=normalized_retention_ratio,
        )

    def as_dict(self) -> dict[str, int | float]:
        return {
            "system_prompt_limit": self.system_prompt_limit,
            "retention_limit": self.retention_limit,
            "resident_limit": self.resident_limit,
            "dialogue_limit": self.dialogue_limit,
            "buffer_limit": self.buffer_limit,
            "memory_token_limit": self.memory_token_limit,
            "summary_token_limit": self.summary_token_limit,
            "notebook_total_token_limit": self.notebook_total_token_limit,
            "memory_capacity_ratio": self.memory_capacity_ratio,
            "notebook_capacity_ratio": self.notebook_capacity_ratio,
            "dialogue_summary_ratio": self.dialogue_summary_ratio,
            "retention_ratio": self.retention_ratio,
            "total_limit": self.total_limit,
            "compression_trigger": self.compression_trigger,
        }
