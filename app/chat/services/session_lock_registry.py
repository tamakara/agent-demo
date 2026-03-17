"""聊天会话级并发锁注册表。"""

from __future__ import annotations

import asyncio


class SessionLockRegistry:
    """按 ``(user_id, session_id)`` 管理异步锁。"""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def get_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """返回会话锁；不存在时自动创建。"""
        key = (user_id, session_id)
        async with self._guard:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

