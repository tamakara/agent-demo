"""Gemini Tokenizer 计数器实现。"""

from __future__ import annotations

import os
from typing import Any

from google import genai

from app.ports.repositories import TokenCounterPort


DEFAULT_TOKENIZER_MODEL = "gemini-3-flash"
SUPPORTED_TOKENIZER_MODELS = ("gemini-3-flash", "gemini-3.1-pro")


class GeminiTokenizerCounter(TokenCounterPort):
    """基于官方 Gemini SDK 的 token 计数器。"""

    def __init__(self) -> None:
        """初始化 SDK 客户端与降级状态。"""
        self._client: genai.Client | None = None
        self._disabled_remote_models: set[str] = set()
        self._api_key = (
            os.getenv("GOOGLE_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
        )

    @staticmethod
    def _normalize_tokenizer_model(model: str) -> str:
        """规范化 tokenizer 选型，未知值回退默认模型。"""
        normalized = str(model or "").strip().lower()
        if normalized in SUPPORTED_TOKENIZER_MODELS:
            return normalized
        return DEFAULT_TOKENIZER_MODEL

    def _get_client(self) -> genai.Client:
        """按需构建并缓存 Gemini Client。"""
        if self._client is not None:
            return self._client
        if self._api_key:
            self._client = genai.Client(api_key=self._api_key)
        else:
            self._client = genai.Client()
        return self._client

    @staticmethod
    def _extract_total_tokens(raw: Any) -> int | None:
        """从 SDK 返回对象中提取 ``total_tokens``。"""
        value = getattr(raw, "total_tokens", None)
        if isinstance(value, int):
            return value
        if isinstance(raw, dict):
            maybe = raw.get("total_tokens")
            if isinstance(maybe, int):
                return maybe
        if hasattr(raw, "model_dump"):
            dumped = raw.model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                maybe = dumped.get("total_tokens")
                if isinstance(maybe, int):
                    return maybe
        return None

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """在 SDK 不可用时使用轻量估算保证流程可用。"""
        if not text:
            return 0
        ascii_chars = sum(1 for ch in text if ch.isascii())
        non_ascii_chars = len(text) - ascii_chars
        estimated = (ascii_chars // 4) + non_ascii_chars
        return max(1, estimated)

    def count_tokens(self, text: str, model: str) -> int:
        """使用 Gemini SDK 统计 token 数。"""
        normalized_text = text or ""
        if not normalized_text:
            return 0

        tokenizer_model = self._normalize_tokenizer_model(model)
        if tokenizer_model in self._disabled_remote_models:
            return self._estimate_tokens(normalized_text)

        try:
            client = self._get_client()
            result = client.models.count_tokens(
                model=tokenizer_model,
                contents=normalized_text,
            )
            total_tokens = self._extract_total_tokens(result)
            if isinstance(total_tokens, int):
                return max(0, total_tokens)
        except Exception:  # noqa: BLE001
            # 远端不可用时降级估算，避免对话主流程失败。
            self._disabled_remote_models.add(tokenizer_model)

        return self._estimate_tokens(normalized_text)

    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:
        """按 token 上限截断文本。"""
        if limit <= 0:
            return ""

        normalized_text = text or ""
        if not normalized_text:
            return ""
        if self.count_tokens(normalized_text, model) <= limit:
            return normalized_text

        # 使用二分查找缩短文本长度，减少 SDK 调用次数。
        lo, hi = 0, len(normalized_text)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = normalized_text[:mid]
            if self.count_tokens(candidate, model) <= limit:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return best.rstrip()
