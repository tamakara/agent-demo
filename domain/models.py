"""领域层核心数据模型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LLMConfig:
    """单次 LLM 调用配置。"""
    model: str
    api_key: str
    base_url: str | None


@dataclass(slots=True)
class GlobalSettings:
    """用户级全局设置。"""
    user_id: str
    model: str
    api_key: str
    base_url: str | None
    max_tool_rounds: int
    total_token_limit: int


@dataclass(slots=True)
class SessionEntry:
    """会话列表条目。"""
    user_id: str
    session_id: str
    is_flushing: bool
    created_at: str
    updated_at: str
    message_count: int


@dataclass(slots=True)
class SessionMessage:
    """会话消息条目。"""
    id: int
    user_id: str
    session_id: str
    role: str
    content: str
    zone: str
    created_at: str


@dataclass(slots=True)
class ChatProcessResult:
    """聊天处理结果。"""
    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    status: MemoryStatus
    flush_scheduled: bool


@dataclass(slots=True)
class LLMRunResult:
    """LLM 执行结果。"""
    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    working_messages: list[dict[str, Any]]
    reached_tool_limit: bool = False


@dataclass(slots=True)
class MemoryFileEntry:
    """记忆文件条目。"""
    file_name: str
    content: str


@dataclass(slots=True)
class MemoryStatus:
    """会话记忆状态。"""
    user_id: str
    session_id: str
    total_tokens: int
    resident_tokens: int
    dialogue_tokens: int
    buffer_tokens: int
    is_flushing: bool
    thresholds: dict[str, int]


@dataclass(slots=True)
class FlushResult:
    """手动刷盘结果。"""
    accepted: bool
    user_id: str
    session_id: str
    is_flushing: bool
