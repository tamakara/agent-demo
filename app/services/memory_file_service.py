"""兼容入口：转发到 ``app.storage.services``。"""

from app.storage.services.memory_file_service import MemoryFileService

__all__ = ["MemoryFileService"]

