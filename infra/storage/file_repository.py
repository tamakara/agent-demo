"""兼容入口：转发到 ``infra.memory``。"""

from infra.memory.file_repository import FileMemoryRepository

__all__ = ["FileMemoryRepository"]

