"""设置服务：读取与更新用户模型配置。"""

from __future__ import annotations

from app.ports.repositories import UserSettingsRepositoryPort
from domain.models import GlobalSettings


FIXED_MAX_TOOL_ROUNDS = 64


class SettingsService:
    """用户设置服务。"""
    def __init__(self, settings_repo: UserSettingsRepositoryPort) -> None:
        """注入用户设置仓储。"""
        self.settings_repo = settings_repo

    async def get_settings(self, user_id: str) -> GlobalSettings:
        """读取用户全局设置。"""
        return await self.settings_repo.get_global_settings(user_id)

    async def update_settings(
        self,
        *,
        user_id: str,
        model: str,
        api_key: str,
        base_url: str | None,
        total_token_limit: int,
        tokenizer_model: str,
    ) -> GlobalSettings:
        """更新用户全局设置并返回最新值。"""
        settings = GlobalSettings(
            user_id=user_id,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tool_rounds=FIXED_MAX_TOOL_ROUNDS,
            total_token_limit=total_token_limit,
            tokenizer_model=tokenizer_model,
        )
        return await self.settings_repo.update_global_settings(settings)
