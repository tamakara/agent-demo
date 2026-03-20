"""Resolve window thresholds and tokenizer choice from user settings."""

from __future__ import annotations

from app.interfaces import ISettingsRepository
from app.window_policy import DEFAULT_TOTAL_LIMIT, WindowThresholds


DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"
TOKENIZER_MODEL_OPTIONS = {DEFAULT_TOKENIZER_MODEL}


class WindowConfigService:
    def __init__(self, settings_repo: ISettingsRepository) -> None:
        self.settings_repo = settings_repo

    @staticmethod
    def normalize_tokenizer_model(tokenizer_model: str | None, fallback_model: str) -> str:
        normalized = str(tokenizer_model or "").strip().lower()
        if normalized in TOKENIZER_MODEL_OPTIONS:
            return normalized
        fallback = str(fallback_model or "").strip().lower()
        if fallback in TOKENIZER_MODEL_OPTIONS:
            return fallback
        return DEFAULT_TOKENIZER_MODEL

    async def get_window_config(
        self,
        user_id: str,
        *,
        fallback_model: str = DEFAULT_TOKENIZER_MODEL,
    ) -> tuple[WindowThresholds, str]:
        settings = await self.settings_repo.get_global_settings(user_id)
        total_limit = settings.total_token_limit
        try:
            parsed_total_limit = int(total_limit)
        except Exception:  # noqa: BLE001
            parsed_total_limit = DEFAULT_TOTAL_LIMIT
        tokenizer_model = self.normalize_tokenizer_model(
            settings.tokenizer_model,
            fallback_model=fallback_model,
        )
        return WindowThresholds.from_total_limit(parsed_total_limit), tokenizer_model
