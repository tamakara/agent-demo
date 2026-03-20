"""Domain layer data models.

This package intentionally contains only pure data structures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GlobalSettings:
    """User-level runtime configuration."""

    user_id: str
    model: str
    api_key: str
    base_url: str | None
    max_tool_rounds: int
    total_token_limit: int
    tokenizer_model: str
    deep_thinking_enabled: bool = False


@dataclass(slots=True, frozen=True)
class LLMConfig:
    """Resolved per-request LLM configuration."""

    model: str
    api_key: str
    base_url: str | None
    total_token_limit: int
    tokenizer_model: str
    max_tool_rounds: int
    deep_thinking_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: GlobalSettings) -> "LLMConfig":
        return cls(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            total_token_limit=int(settings.total_token_limit),
            tokenizer_model=settings.tokenizer_model,
            max_tool_rounds=int(settings.max_tool_rounds),
            deep_thinking_enabled=bool(settings.deep_thinking_enabled),
        )


@dataclass(slots=True)
class EmployeeEntry:
    user_id: str
    employee_id: str
    session_id: str
    is_compressing: bool
    created_at: str
    updated_at: str
    message_count: int


@dataclass(slots=True)
class EmployeeMessage:
    id: int
    user_id: str
    employee_id: str
    session_id: str
    role: str
    message_kind: str
    content: str
    zone: str
    created_at: str


@dataclass(slots=True)
class MemoryFileEntry:
    file_name: str
    relative_path: str
    content: str


@dataclass(slots=True)
class MemoryStatus:
    user_id: str
    employee_id: str
    session_id: str
    total_tokens: int
    resident_tokens: int
    dialogue_tokens: int
    buffer_tokens: int
    is_compressing: bool
    thresholds: dict[str, int]


@dataclass(slots=True)
class LLMRunResult:
    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    working_messages: list[dict[str, Any]]
    reached_tool_limit: bool = False


@dataclass(slots=True)
class ChatResult:
    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    status: MemoryStatus
    compression_scheduled: bool


@dataclass(slots=True)
class CompressionResult:
    accepted: bool
    user_id: str
    employee_id: str
    session_id: str
    is_compressing: bool
