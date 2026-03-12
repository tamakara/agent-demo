"""API 请求体 DTO 与字段校验规则。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


TOKENIZER_MODEL_OPTIONS = ("gemini-3-flash", "gemini-3.1-pro")
DEFAULT_TOKENIZER_MODEL = "gemini-3-flash"


def ensure_string(value: Any) -> str:
    """确保输入值是字符串类型。"""
    if not isinstance(value, str):
        raise TypeError("字段类型必须是字符串")
    return value


def strip_required_text(value: Any) -> str:
    """清理首尾空白并校验必填文本。"""
    text = ensure_string(value).strip()
    if not text:
        raise ValueError("字段不能为空")
    return text


def strip_optional_text(value: Any) -> str | None:
    """清理可选文本，空字符串归一为 ``None``。"""
    if value is None:
        return None
    text = ensure_string(value).strip()
    return text or None


class EmployeeCreateRequest(BaseModel):
    """创建数字员工请求体。"""

    user_id: str = Field(..., min_length=1)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: Any) -> str:
        """规范化 ``user_id``。"""
        return strip_required_text(value)


class ChatStreamRequest(BaseModel):
    """聊天流请求体。"""

    user_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    employee_id: str = Field(default="1", min_length=1)

    @field_validator("user_id", "message", "employee_id", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        """规范化必填文本字段。"""
        return strip_required_text(value)


class MemoryFileUpdateRequest(BaseModel):
    """记忆文件更新请求体。"""

    content: str
    mode: Literal["overwrite", "append"] = "overwrite"


class FlushRequest(BaseModel):
    """手动触发记忆刷盘请求体。"""

    user_id: str = Field(..., min_length=1)
    employee_id: str = Field(default="1", min_length=1)

    @field_validator("user_id", "employee_id", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        """规范化必填文本字段。"""
        return strip_required_text(value)


class SettingsUpdateRequest(BaseModel):
    """用户设置更新请求体。"""

    user_id: str = Field(..., min_length=1)
    model: str = Field(default="agent-advoo")
    api_key: str = Field(default="")
    base_url: str | None = Field(default="http://model-gateway.test.api.dotai.internal/v1")
    total_token_limit: int = Field(default=200000, ge=20000, le=2000000)
    tokenizer_model: Literal["gemini-3-flash", "gemini-3.1-pro"] = Field(default=DEFAULT_TOKENIZER_MODEL)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: Any) -> str:
        """规范化 ``user_id``。"""
        return strip_required_text(value)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: Any) -> str:
        """规范化 ``model``，为空时回退默认模型。"""
        if value is None:
            return "agent-advoo"
        model = ensure_string(value).strip()
        return model or "agent-advoo"

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: Any) -> str:
        """规范化 ``api_key``。"""
        if value is None:
            return ""
        return ensure_string(value).strip()

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: Any) -> str | None:
        """规范化 ``base_url``，为空时回退默认网关地址。"""
        return strip_optional_text(value) or "http://model-gateway.test.api.dotai.internal/v1"

    @field_validator("total_token_limit", mode="before")
    @classmethod
    def normalize_token_limit(cls, value: Any) -> int:
        """将 token 限额转为整数并校验类型。"""
        if value is None or value == "":
            return 200000
        if isinstance(value, bool):
            raise TypeError("字段类型必须是整数")
        try:
            return int(value)
        except Exception as exc:  # noqa: BLE001
            raise TypeError("字段类型必须是整数") from exc

    @field_validator("tokenizer_model", mode="before")
    @classmethod
    def normalize_tokenizer_model(cls, value: Any) -> str:
        """规范化 tokenizer 选项。"""
        if value is None:
            return DEFAULT_TOKENIZER_MODEL
        text = ensure_string(value).strip().lower()
        if not text:
            return DEFAULT_TOKENIZER_MODEL
        if text not in TOKENIZER_MODEL_OPTIONS:
            raise ValueError(f"tokenizer_model 仅支持: {', '.join(TOKENIZER_MODEL_OPTIONS)}")
        return text
