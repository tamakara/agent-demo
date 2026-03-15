"""聊天窗口阈值与 tokenizer 选择服务。"""

from __future__ import annotations

from app.ports.repositories import UserSettingsRepositoryPort
from domain.window_policy import DEFAULT_TOTAL_LIMIT, WindowThresholds


DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"
TOKENIZER_MODEL_OPTIONS = {DEFAULT_TOKENIZER_MODEL}


class WindowConfigService:
    """读取并标准化用户窗口配置。"""

    def __init__(self, settings_repo: UserSettingsRepositoryPort) -> None:
        self.settings_repo = settings_repo

    @staticmethod
    def normalize_tokenizer_model(tokenizer_model: str | None, fallback_model: str) -> str:
        """规范化用户配置的 tokenizer 模型名。"""
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
        """读取 token 窗口阈值与 tokenizer 选型。"""
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

