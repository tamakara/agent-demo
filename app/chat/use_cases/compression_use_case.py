"""压缩用例：控制手动与自动压缩流程。"""

from __future__ import annotations

from app.chat.services.memory_context_service import MemoryContextService
from domain.models import CompressionResult, LLMConfig


class CompressionUseCase:
    """手动/自动压缩编排。"""

    def __init__(self, memory_context: MemoryContextService) -> None:
        """注入记忆上下文服务。"""
        self.memory_context = memory_context

    async def try_start_manual_compression(self, *, user_id: str, session_id: str) -> bool:
        """尝试抢占手动压缩执行权。"""
        return await self.memory_context.try_start_manual_compression(user_id, session_id)

    async def compress(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
    ) -> None:
        """执行一次会话压缩流程。"""
        await self.memory_context.compress_session_memory(
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            llm_config=llm_config,
            max_tool_rounds=max_tool_rounds,
        )

    async def execute_manual(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
    ) -> CompressionResult:
        """执行手动压缩并返回压缩状态。"""
        accepted = await self.try_start_manual_compression(user_id=user_id, session_id=session_id)
        if accepted:
            await self.compress(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                llm_config=llm_config,
                max_tool_rounds=max_tool_rounds,
            )
        status = await self.memory_context.get_status(user_id, employee_id, session_id, llm_config.model)
        return CompressionResult(
            accepted=accepted,
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            is_compressing=status.is_compressing,
        )


