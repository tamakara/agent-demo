"""tiktoken 计数器适配实现。"""

from __future__ import annotations

import tiktoken

from app.ports.repositories import TokenCounterPort


class TiktokenCounter(TokenCounterPort):
    """tiktoken 计数适配器。"""

    @staticmethod
    def _encoding_for_model(model: str) -> tiktoken.Encoding:
        """获取模型对应编码；未知模型时回退到通用编码。"""
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:  # noqa: BLE001
            return tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str, model: str) -> int:
        """统计 token 数量。"""
        normalized = text or ""
        encoding = self._encoding_for_model(model)
        return len(encoding.encode(normalized))

    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:
        """按约束截断内容。"""
        if limit <= 0:
            return ""
        normalized = text or ""
        encoding = self._encoding_for_model(model)
        encoded = encoding.encode(normalized)
        if len(encoded) <= limit:
            return normalized
        return encoding.decode(encoded[:limit]).rstrip()

