"""兼容入口：转发到 ``app.chat.services``。"""

from app.chat.services.memory_context_service import MemoryContextService

__all__ = ["MemoryContextService"]

