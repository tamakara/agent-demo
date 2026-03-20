"""Window budget policy used by application services."""

from __future__ import annotations

from dataclasses import dataclass

from app.memory_specs import SYSTEM_PROMPT_LIMIT_RATIO


DEFAULT_TOTAL_LIMIT = 200_000
MIN_TOTAL_LIMIT = 20_000
SYSTEM_PROMPT_PERCENT = int(round(SYSTEM_PROMPT_LIMIT_RATIO * 100))
SUMMARY_PERCENT = 1
RECENT_RAW_PERCENT = 9


@dataclass(slots=True, frozen=True)
class WindowThresholds:
    total_limit: int
    system_prompt_limit: int
    summary_limit: int
    recent_raw_limit: int
    recent_total_limit: int
    resident_limit: int
    dialogue_limit: int
    buffer_limit: int
    compression_trigger: int

    @classmethod
    def from_total_limit(cls, total_limit: int) -> "WindowThresholds":
        normalized = max(MIN_TOTAL_LIMIT, int(total_limit))
        system_prompt_limit = max(1, (normalized * SYSTEM_PROMPT_PERCENT) // 100)
        summary_limit = max(1, (normalized * SUMMARY_PERCENT) // 100)
        recent_raw_limit = max(1, (normalized * RECENT_RAW_PERCENT) // 100)
        recent_total_limit = summary_limit + recent_raw_limit
        resident_limit = system_prompt_limit + recent_total_limit
        dialogue_limit = max(1, normalized - resident_limit)
        buffer_limit = dialogue_limit
        return cls(
            total_limit=normalized,
            system_prompt_limit=system_prompt_limit,
            summary_limit=summary_limit,
            recent_raw_limit=recent_raw_limit,
            recent_total_limit=recent_total_limit,
            resident_limit=resident_limit,
            dialogue_limit=dialogue_limit,
            buffer_limit=buffer_limit,
            compression_trigger=normalized,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "system_prompt_limit": self.system_prompt_limit,
            "summary_limit": self.summary_limit,
            "recent_raw_limit": self.recent_raw_limit,
            "recent_total_limit": self.recent_total_limit,
            "resident_limit": self.resident_limit,
            "dialogue_limit": self.dialogue_limit,
            "buffer_limit": self.buffer_limit,
            "total_limit": self.total_limit,
            "compression_trigger": self.compression_trigger,
        }
