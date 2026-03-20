"""会话级异步锁注册表。

作用：
- 对同一个 `(user_id, session_id)` 维度的操作串行化，
  避免并发写入造成状态错乱（尤其是聊天写消息与压缩流程并发时）。
"""

from __future__ import annotations

import asyncio


class SessionLockRegistry:
    """管理会话锁的轻量注册表。"""

    def __init__(self) -> None:
        # key: (user_id, session_id)；value: 对应会话锁。
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        # 全局保护锁：用于保护 _locks 字典本身的并发读写。
        self._guard = asyncio.Lock()

    async def get_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """获取指定会话锁；若不存在则原子创建。"""
        key = (user_id, session_id)
        async with self._guard:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]
