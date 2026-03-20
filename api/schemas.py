"""REST 入参模型（Pydantic DTO）。

该模块负责：
- 请求体字段定义。
- 基础字段规范化与校验。

注意：
- 这里只做协议层校验，不承载业务决策。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


TOKENIZER_MODEL_OPTIONS = ("kimi-k2.5",)
DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"


def ensure_string(value: Any) -> str:
    """确保值是字符串类型。"""
    if not isinstance(value, str):
        raise TypeError("字段类型必须是字符串")
    return value


def strip_required_text(value: Any) -> str:
    """去除首尾空白并校验必填字符串。"""
    text = ensure_string(value).strip()
    if not text:
        raise ValueError("字段不能为空")
    return text


def strip_optional_text(value: Any) -> str | None:
    """可选字符串规范化：空字符串 -> None。"""
    if value is None:
        return None
    text = ensure_string(value).strip()
    return text or None


class ChatStreamBody(BaseModel):
    """流式聊天请求体。"""

    message: str = Field(..., min_length=1)

    @field_validator("message", mode="before")
    @classmethod
    def normalize_message(cls, value: Any) -> str:
        return strip_required_text(value)


class FileContentUpdateBody(BaseModel):
    """文本文件更新请求体。"""

    content: str
    mode: Literal["overwrite", "append"] = "overwrite"


class SettingsUpdateBody(BaseModel):
    """用户设置更新请求体。"""

    model: str = Field(default="agent-advoo")
    api_key: str = Field(default="")
    base_url: str | None = Field(default="http://model-gateway.test.api.dotai.internal/v1")
    total_token_limit: int = Field(default=200000, ge=20000, le=2000000)
    tokenizer_model: Literal["kimi-k2.5"] = Field(default=DEFAULT_TOKENIZER_MODEL)
    deep_thinking_enabled: bool = Field(default=False)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: Any) -> str:
        """模型名为空时回退默认模型。"""
        if value is None:
            return "agent-advoo"
        model = ensure_string(value).strip()
        return model or "agent-advoo"

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: Any) -> str:
        if value is None:
            return ""
        return ensure_string(value).strip()

    @field_validator("base_url", mode="before")
    @classmethod
    def normalize_base_url(cls, value: Any) -> str | None:
        """base_url 为空时回退默认网关。"""
        return strip_optional_text(value) or "http://model-gateway.test.api.dotai.internal/v1"

    @field_validator("total_token_limit", mode="before")
    @classmethod
    def normalize_token_limit(cls, value: Any) -> int:
        """将 token 限额输入统一转成 int。"""
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
        """限制 tokenizer 可选项。"""
        if value is None:
            return DEFAULT_TOKENIZER_MODEL
        text = ensure_string(value).strip().lower()
        if not text:
            return DEFAULT_TOKENIZER_MODEL
        if text not in TOKENIZER_MODEL_OPTIONS:
            raise ValueError(f"tokenizer_model 仅支持: {', '.join(TOKENIZER_MODEL_OPTIONS)}")
        return text

    @field_validator("deep_thinking_enabled", mode="before")
    @classmethod
    def normalize_deep_thinking_enabled(cls, value: Any) -> bool:
        """规范化“深度思考”开关，默认关闭。"""
        if value is None or value == "":
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
        raise TypeError("deep_thinking_enabled 必须是布尔值")
