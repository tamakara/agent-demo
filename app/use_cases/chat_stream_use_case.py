"""聊天流用例：编排对话、工具调用与记忆状态返回。"""

from __future__ import annotations

from app.ports.repositories import EventCallback
from app.use_cases.memory_context import MemoryContextService
from domain.models import ChatProcessResult, LLMConfig


class ChatStreamUseCase:
    """聊天流编排入口。"""

    def __init__(self, memory_context: MemoryContextService) -> None:
        """注入记忆上下文服务。"""
        self.memory_context = memory_context

    async def execute(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        message: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
    ) -> ChatProcessResult:
        """执行聊天流程并返回最终处理结果。"""
        return await self.memory_context.process_chat(
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            user_message=message,
            llm_config=llm_config,
            max_tool_rounds=max_tool_rounds,
            on_event=on_event,
        )
