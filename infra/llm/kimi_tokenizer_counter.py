"""Kimi K2.5 tokenizer 计数器（基于本地 tiktoken 词表）。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Iterator

import tiktoken
from tiktoken.load import load_tiktoken_bpe

from app.ports.repositories import TokenCounterPort


DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"
SUPPORTED_TOKENIZER_MODELS = {DEFAULT_TOKENIZER_MODEL}
NUM_RESERVED_SPECIAL_TOKENS = 256
TIKTOKEN_MAX_ENCODE_CHARS = 400_000
MAX_NO_WHITESPACES_CHARS = 25_000
PAT_STR = "|".join(
    [
        r"""[\p{Han}]+""",
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
        r"""\p{N}{1,3}""",
        r""" ?[^\s\p{L}\p{N}]+[\r\n]*""",
        r"""\s*[\r\n]+""",
        r"""\s+(?!\S)""",
        r"""\s+""",
    ]
)


class KimiTokenizerCounter(TokenCounterPort):
    """Kimi K2.5 本地 tokenizer 计数实现。"""

    def __init__(
        self,
        *,
        vocab_file: Path | str | None = None,
        tokenizer_config_file: Path | str | None = None,
    ) -> None:
        """初始化本地词表与配置路径。"""
        asset_dir = Path(__file__).resolve().parent / "tokenizer_assets"
        self._vocab_file = Path(vocab_file) if vocab_file else asset_dir / "tiktoken.model"
        self._tokenizer_config_file = (
            Path(tokenizer_config_file) if tokenizer_config_file else asset_dir / "tokenizer_config.json"
        )
        self._encoding: tiktoken.Encoding | None = None
        self._encoding_lock = Lock()

    @staticmethod
    def _normalize_tokenizer_model(model: str) -> str:
        """规范化 tokenizer 选型，未知值回退默认模型。"""
        normalized = str(model or "").strip().lower()
        if normalized in SUPPORTED_TOKENIZER_MODELS:
            return normalized
        return DEFAULT_TOKENIZER_MODEL

    def _load_special_tokens_from_config(self) -> dict[int, str]:
        """读取 tokenizer_config.json 中声明的特殊 token 映射。"""
        if not self._tokenizer_config_file.is_file():
            return {}

        try:
            payload = json.loads(self._tokenizer_config_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

        raw_decoder = payload.get("added_tokens_decoder", {})
        if not isinstance(raw_decoder, dict):
            return {}

        mapped: dict[int, str] = {}
        for raw_id, raw_item in raw_decoder.items():
            try:
                token_id = int(raw_id)
            except Exception:  # noqa: BLE001
                continue

            token_text = ""
            if isinstance(raw_item, dict):
                token_text = str(raw_item.get("content", "")).strip()
            else:
                token_text = str(raw_item).strip()
            if token_text:
                mapped[token_id] = token_text
        return mapped

    def _build_encoding(self) -> tiktoken.Encoding:
        """基于词表和配置构建 tiktoken Encoding。"""
        if not self._vocab_file.is_file():
            raise FileNotFoundError(f"找不到 tiktoken 词表文件：{self._vocab_file}")

        mergeable_ranks = load_tiktoken_bpe(str(self._vocab_file))
        num_base_tokens = len(mergeable_ranks)
        lower = num_base_tokens
        upper = num_base_tokens + NUM_RESERVED_SPECIAL_TOKENS

        id_to_special = {token_id: f"<|reserved_token_{token_id}|>" for token_id in range(lower, upper)}
        for token_id, token_text in self._load_special_tokens_from_config().items():
            if lower <= token_id < upper:
                id_to_special[token_id] = token_text

        special_tokens = {token_text: token_id for token_id, token_text in id_to_special.items()}
        return tiktoken.Encoding(
            name=f"kimi-k2.5::{self._vocab_file.name}",
            pat_str=PAT_STR,
            mergeable_ranks=mergeable_ranks,
            special_tokens=special_tokens,
        )

    def _get_encoding(self) -> tiktoken.Encoding:
        """懒加载并缓存 Encoding，避免重复构建。"""
        if self._encoding is not None:
            return self._encoding

        with self._encoding_lock:
            if self._encoding is None:
                self._encoding = self._build_encoding()
        return self._encoding

    @staticmethod
    def _split_whitespaces_or_nonwhitespaces(
        text: str,
        max_consecutive_slice_len: int,
    ) -> Iterator[str]:
        """将输入按连续空白/非空白上限切片，规避 tiktoken 超长片段问题。"""
        current_slice_len = 0
        current_slice_is_space = text[0].isspace() if text else False
        slice_start = 0

        for index, char in enumerate(text):
            now_is_space = char.isspace()
            if current_slice_is_space ^ now_is_space:
                current_slice_len = 1
                current_slice_is_space = now_is_space
                continue

            current_slice_len += 1
            if current_slice_len > max_consecutive_slice_len:
                yield text[slice_start:index]
                slice_start = index
                current_slice_len = 1

        if text:
            yield text[slice_start:]

    def _encode(self, text: str) -> list[int]:
        """执行安全编码并返回 token id 列表。"""
        normalized = text or ""
        if not normalized:
            return []

        encoding = self._get_encoding()
        token_ids: list[int] = []
        for start in range(0, len(normalized), TIKTOKEN_MAX_ENCODE_CHARS):
            chunk = normalized[start : start + TIKTOKEN_MAX_ENCODE_CHARS]
            for piece in self._split_whitespaces_or_nonwhitespaces(
                chunk,
                MAX_NO_WHITESPACES_CHARS,
            ):
                if not piece:
                    continue
                token_ids.extend(encoding.encode(piece, allowed_special="all"))
        return token_ids

    def count_tokens(self, text: str, model: str) -> int:
        """统计文本 token 数。"""
        _ = self._normalize_tokenizer_model(model)
        return len(self._encode(text))

    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:
        """将文本截断到 token 上限内。"""
        if limit <= 0:
            return ""

        _ = self._normalize_tokenizer_model(model)
        normalized = text or ""
        if not normalized:
            return ""

        token_ids = self._encode(normalized)
        if len(token_ids) <= limit:
            return normalized

        truncated = self._get_encoding().decode(token_ids[:limit])
        return truncated.rstrip()
