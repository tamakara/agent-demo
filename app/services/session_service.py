"""会话服务：提供会话及消息访问能力。"""

from __future__ import annotations

from app.ports.repositories import MessageRepositoryPort, SessionRepositoryPort
from domain.models import SessionEntry, SessionMessage
from common.ids import new_session_id


class SessionService:
    """会话读写服务。"""
    def __init__(self, session_repo: SessionRepositoryPort, message_repo: MessageRepositoryPort) -> None:
        """注入会话仓储与消息仓储。"""
        self.session_repo = session_repo
        self.message_repo = message_repo

    @staticmethod
    def _build_session_entry(data: dict[str, object]) -> SessionEntry:
        """将仓储层字典对象转换为 ``SessionEntry``。"""
        return SessionEntry(
            user_id=str(data.get("user_id", "")),
            session_id=str(data.get("session_id", "")),
            is_flushing=bool(data.get("is_flushing", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            message_count=int(data.get("message_count", 0)),
        )

    @staticmethod
    def _build_session_message_entry(data: dict[str, object]) -> SessionMessage:
        """将仓储层字典对象转换为 ``SessionMessage``。"""
        return SessionMessage(
            id=int(data.get("id", 0)),
            user_id=str(data.get("user_id", "")),
            session_id=str(data.get("session_id", "")),
            role=str(data.get("role", "")),
            content=str(data.get("content", "")),
            zone=str(data.get("zone", "")),
            created_at=str(data.get("created_at", "")),
        )

    async def list_sessions(self, user_id: str, *, limit: int = 300) -> list[SessionEntry]:
        """查询用户会话列表。"""
        rows = await self.session_repo.list_sessions(user_id, limit=limit)
        return [self._build_session_entry(row) for row in rows]

    async def create_session(self, user_id: str, session_id: str | None = None) -> SessionEntry:
        """创建会话，未提供 session_id 时自动生成。"""
        normalized_session_id = (session_id or "").strip() or new_session_id()
        session = await self.session_repo.create_session(user_id, normalized_session_id)
        return self._build_session_entry({**session, "message_count": 0})

    async def list_session_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        limit: int = 500,
    ) -> list[SessionMessage]:
        """查询指定会话消息列表。"""
        rows = await self.message_repo.list_messages(
            user_id=user_id,
            session_id=session_id,
            ascending=True,
            limit=limit,
        )
        return [self._build_session_message_entry(row) for row in rows]

