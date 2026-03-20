"""用户设置应用服务。

该服务负责：
1. 读取用户全局模型设置。
2. 将设置转换为单次调用所需的 LLMConfig。
3. 更新用户设置时补齐系统固定策略（如最大工具轮次）。

注意：
- 服务本身不关心数据库细节，只依赖 ISettingsRepository 抽象。
"""

from __future__ import annotations

from app.interfaces import ISettingsRepository
from domain.models import GlobalSettings, LLMConfig


# 系统级固定上限：防止异常配置导致工具循环无限扩张。
FIXED_MAX_TOOL_ROUNDS = 64


class SettingsService:
    """用户设置服务。"""

    def __init__(self, settings_repo: ISettingsRepository) -> None:
        # 通过依赖注入接入仓储，便于替换实现（SQLite/Mock/其他存储）。
        self.settings_repo = settings_repo

    async def get_settings(self, user_id: str) -> GlobalSettings:
        """读取用户全局设置。"""
        return await self.settings_repo.get_global_settings(user_id)

    async def get_llm_config(self, user_id: str) -> LLMConfig:
        """基于全局设置构建本次请求可直接使用的 LLM 配置对象。"""
        settings = await self.get_settings(user_id)
        return LLMConfig.from_settings(settings)

    async def update_settings(
        self,
        *,
        user_id: str,
        model: str,
        api_key: str,
        base_url: str | None,
        total_token_limit: int,
        tokenizer_model: str,
        deep_thinking_enabled: bool,
    ) -> GlobalSettings:
        """更新用户设置。

        这里会把 `max_tool_rounds` 强制写为系统固定值，
        避免外部任意配置破坏稳定性。
        """
        settings = GlobalSettings(
            user_id=user_id,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tool_rounds=FIXED_MAX_TOOL_ROUNDS,
            total_token_limit=total_token_limit,
            tokenizer_model=tokenizer_model,
            deep_thinking_enabled=bool(deep_thinking_enabled),
        )
        return await self.settings_repo.update_global_settings(settings)
