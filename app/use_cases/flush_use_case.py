"""刷盘用例：控制手动与自动刷盘流程。"""

from __future__ import annotations

from app.use_cases.memory_context import MemoryContextService
from domain.models import FlushResult, LLMConfig


class FlushUseCase:
    """手动/自动刷盘编排。"""

    def __init__(self, memory_context: MemoryContextService) -> None:
        """注入记忆上下文服务。"""
        self.memory_context = memory_context

    async def try_start_manual_flush(self, *, user_id: str, session_id: str) -> bool:
        """尝试抢占手动刷盘执行权。"""
        return await self.memory_context.try_start_manual_flush(user_id, session_id)

    async def flush(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
    ) -> None:
        """执行一次会话刷盘流程。"""
        await self.memory_context.flush_session_memory(
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
    ) -> FlushResult:
        """执行手动刷盘并返回刷盘状态。"""
        accepted = await self.try_start_manual_flush(user_id=user_id, session_id=session_id)
        if accepted:
            await self.flush(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                llm_config=llm_config,
                max_tool_rounds=max_tool_rounds,
            )
        status = await self.memory_context.get_status(user_id, employee_id, session_id, llm_config.model)
        return FlushResult(
            accepted=accepted,
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            is_flushing=status.is_flushing,
        )
