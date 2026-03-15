"""兼容入口：转发到 ``infra.sqlite``。"""

from infra.sqlite.repository import SQLiteRepository

__all__ = ["SQLiteRepository"]

