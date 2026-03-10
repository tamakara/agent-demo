"""接口请求与响应模型定义。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _ensure_string(value: Any) -> str:
    """统一字符串类型校验，保持错误文案一致。"""
    if not isinstance(value, str):
        raise TypeError("字段类型必须是字符串")
    return value


def _strip_required_text(value: Any) -> str:
    """
    处理“必填字符串”字段：
    1) 要求类型必须为 str。
    2) 自动去除首尾空白。
    3) 去空白后不能为空。
    """
    text = _ensure_string(value).strip()
    if not text:
        raise ValueError("字段不能为空")
    return text


def _strip_optional_text(value: Any) -> str | None:
    """处理“可选字符串”字段：None 保留，字符串会去空白并把空串转为 None。"""
    if value is None:
        return None
    text = _ensure_string(value).strip()
    return text or None


class LLMConfig(BaseModel):
    """前端每次请求动态传入的 LLM 配置。"""

    model: str = Field(..., min_length=1)
    api_key: str = Field(..., min_length=1)
    base_url: str | None = None

    @field_validator("model", "api_key", mode="before")
    @classmethod
    def _strip_required(cls, value: Any) -> str:
        return _strip_required_text(value)

    @field_validator("base_url", mode="before")
    @classmethod
    def _strip_optional(cls, value: Any) -> str | None:
        return _strip_optional_text(value)


class ChatRequest(BaseModel):
    """聊天接口请求体。"""

    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    session_id: str = Field(default="default", min_length=1)
    max_tool_rounds: int = Field(default=6, ge=1, le=20)
    llm_config: LLMConfig

    @field_validator("user_id", "message", "session_id", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> str:
        return _strip_required_text(value)


class FlushRequest(BaseModel):
    """手动刷盘请求体。"""

    user_id: str = Field(..., min_length=1)
    session_id: str = Field(default="default", min_length=1)
    max_tool_rounds: int = Field(default=6, ge=1, le=20)
    llm_config: LLMConfig

    @field_validator("user_id", "session_id", mode="before")
    @classmethod
    def _strip_session_id(cls, value: Any) -> str:
        return _strip_required_text(value)


class MemoryFileUpdateRequest(BaseModel):
    """记忆文件更新请求体。"""

    content: str
    mode: Literal["overwrite", "append"] = "overwrite"


class MemoryStatusResponse(BaseModel):
    """记忆窗口状态响应体。"""

    user_id: str
    session_id: str
    total_tokens: int
    resident_tokens: int
    dialogue_tokens: int
    buffer_tokens: int
    is_flushing: bool
    thresholds: dict[str, int]


class MemoryFileEntry(BaseModel):
    file_name: str
    content: str


class MemoryFilesResponse(BaseModel):
    files: list[MemoryFileEntry]


class FlushResponse(BaseModel):
    accepted: bool
    user_id: str
    session_id: str
    is_flushing: bool


class SessionCreateRequest(BaseModel):
    """创建会话请求体（可选指定 session_id）。"""

    user_id: str = Field(..., min_length=1)
    session_id: str | None = None

    @field_validator("user_id", mode="before")
    @classmethod
    def _strip_user_id(cls, value: Any) -> str:
        return _strip_required_text(value)

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_session_id_optional(cls, value: Any) -> str | None:
        return _strip_optional_text(value)


class SessionEntry(BaseModel):
    user_id: str
    session_id: str
    is_flushing: bool
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionListResponse(BaseModel):
    sessions: list[SessionEntry]


class SessionCreateResponse(BaseModel):
    created: bool
    session: SessionEntry


class SessionMessageEntry(BaseModel):
    id: int
    user_id: str
    session_id: str
    role: str
    content: str
    zone: str
    created_at: str


class SessionMessagesResponse(BaseModel):
    user_id: str
    session_id: str
    messages: list[SessionMessageEntry]


class GlobalLLMConfig(BaseModel):
    """全局设置（存储于 SQLite app_settings）。"""

    model: str = Field(default="agent-advoo")
    api_key: str = Field(default="sk-RtSmDDQfUbbrNczdVajJqoozIR8AYolUOWwSTgpc2s7rZq6F")
    base_url: str | None = Field(default="http://model-gateway.test.api.dotai.internal/v1")
    max_tool_rounds: int = Field(default=6, ge=1, le=20)
    total_token_limit: int = Field(default=200000, ge=20000, le=2000000)

    @field_validator("model", mode="before")
    @classmethod
    def _strip_model(cls, value: Any) -> str:
        if value is None:
            return "agent-advoo"
        model = _ensure_string(value).strip()
        return model or "agent-advoo"

    @field_validator("api_key", mode="before")
    @classmethod
    def _strip_api_key(cls, value: Any) -> str:
        if value is None:
            return ""
        return _ensure_string(value).strip()

    @field_validator("base_url", mode="before")
    @classmethod
    def _strip_base_url(cls, value: Any) -> str | None:
        return _strip_optional_text(value) or "http://model-gateway.test.api.dotai.internal/v1"

    @field_validator("total_token_limit", mode="before")
    @classmethod
    def _normalize_total_token_limit(cls, value: Any) -> int:
        if value is None or value == "":
            return 200000
        if isinstance(value, bool):
            raise TypeError("字段类型必须是整数")
        try:
            return int(value)
        except Exception as exc:  # noqa: BLE001
            raise TypeError("字段类型必须是整数") from exc
