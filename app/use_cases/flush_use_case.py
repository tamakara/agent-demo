"""兼容入口：转发到 ``app.chat.use_cases``。"""

from app.chat.use_cases.flush_use_case import FlushUseCase

__all__ = ["FlushUseCase"]

