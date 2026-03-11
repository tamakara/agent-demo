"""记忆状态用例：聚合并返回当前会话记忆状态。"""

from __future__ import annotations

from app.use_cases.memory_context import MemoryContextService
from domain.models import MemoryStatus


class MemoryStatusUseCase:
    """记忆状态查询用例。"""
    def __init__(self, memory_context: MemoryContextService) -> None:
        """注入记忆上下文服务。"""
        self.memory_context = memory_context

    async def execute(self, *, user_id: str, employee_id: str, session_id: str, model: str) -> MemoryStatus:
        """查询并返回会话记忆状态。"""
        return await self.memory_context.get_status(
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            model=model,
        )
