"""数字员工服务：提供员工及消息访问能力。"""

from __future__ import annotations

from app.ports.repositories import MessageRepositoryPort, SessionRepositoryPort
from common.errors import NotFoundError
from common.ids import employee_id_from_session_id, normalize_employee_id, session_id_from_employee_id
from domain.models import EmployeeEntry, EmployeeMessage


class EmployeeService:
    """数字员工读写服务。"""

    def __init__(self, session_repo: SessionRepositoryPort, message_repo: MessageRepositoryPort) -> None:
        """注入会话仓储与消息仓储。"""
        self.session_repo = session_repo
        self.message_repo = message_repo

    @staticmethod
    def _build_employee_entry(data: dict[str, object]) -> EmployeeEntry:
        """将仓储层字典对象转换为 ``EmployeeEntry``。"""
        session_id = str(data.get("session_id", ""))
        employee_id = employee_id_from_session_id(session_id) or ""
        return EmployeeEntry(
            user_id=str(data.get("user_id", "")),
            employee_id=employee_id,
            session_id=session_id,
            is_flushing=bool(data.get("is_flushing", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            message_count=int(data.get("message_count", 0)),
        )

    @staticmethod
    def _build_employee_message_entry(data: dict[str, object], employee_id: str) -> EmployeeMessage:
        """将仓储层字典对象转换为 ``EmployeeMessage``。"""
        return EmployeeMessage(
            id=int(data.get("id", 0)),
            user_id=str(data.get("user_id", "")),
            employee_id=employee_id,
            session_id=str(data.get("session_id", "")),
            role=str(data.get("role", "")),
            content=str(data.get("content", "")),
            zone=str(data.get("zone", "")),
            created_at=str(data.get("created_at", "")),
        )

    async def _list_employee_rows(self, user_id: str, *, limit: int = 5000) -> list[dict[str, object]]:
        """读取用户全部员工会话行。"""
        rows = await self.session_repo.list_sessions(user_id, limit=limit)
        employee_rows: list[dict[str, object]] = []
        for row in rows:
            session_id = str(row.get("session_id", ""))
            employee_id = employee_id_from_session_id(session_id)
            if not employee_id:
                continue
            employee_rows.append(dict(row))
        return employee_rows

    async def ensure_default_employee(self, user_id: str) -> EmployeeEntry:
        """确保 1 号员工存在并返回其信息。"""
        default_employee_id = "1"
        default_session_id = session_id_from_employee_id(default_employee_id)
        await self.session_repo.ensure_session(user_id, default_session_id)
        session = await self.session_repo.get_session(user_id, default_session_id)
        return self._build_employee_entry({**session, "message_count": 0})

    async def list_employees(self, user_id: str, *, limit: int = 300) -> list[EmployeeEntry]:
        """查询用户数字员工列表。"""
        await self.ensure_default_employee(user_id)
        rows = await self._list_employee_rows(user_id, limit=max(5000, limit * 5))
        entries = [self._build_employee_entry(row) for row in rows]
        entries = [entry for entry in entries if entry.employee_id]
        entries.sort(key=lambda entry: int(entry.employee_id))
        return entries[:limit]

    async def create_employee(self, user_id: str) -> EmployeeEntry:
        """创建新数字员工，编号按当前最大值递增。"""
        existing = await self.list_employees(user_id, limit=5000)
        max_id = max((int(item.employee_id) for item in existing), default=0)
        next_employee_id = str(max_id + 1)
        session_id = session_id_from_employee_id(next_employee_id)
        session = await self.session_repo.create_session(user_id, session_id)
        return self._build_employee_entry({**session, "message_count": 0})

    async def get_employee(self, user_id: str, employee_id: str, *, auto_create_default: bool = True) -> EmployeeEntry:
        """读取指定数字员工；可选自动创建默认 1 号员工。"""
        normalized_employee_id = normalize_employee_id(employee_id)
        if normalized_employee_id == "1" and auto_create_default:
            await self.ensure_default_employee(user_id)

        target_session_id = session_id_from_employee_id(normalized_employee_id)
        rows = await self._list_employee_rows(user_id, limit=5000)
        for row in rows:
            if str(row.get("session_id", "")) == target_session_id:
                return self._build_employee_entry(row)

        raise NotFoundError(f"数字员工不存在：employee_id={normalized_employee_id}")

    async def list_employee_messages(
        self,
        user_id: str,
        employee_id: str,
        *,
        limit: int = 500,
    ) -> list[EmployeeMessage]:
        """查询指定数字员工消息列表。"""
        employee = await self.get_employee(user_id, employee_id)
        rows = await self.message_repo.list_messages(
            user_id=user_id,
            session_id=employee.session_id,
            ascending=True,
            limit=limit,
        )
        return [self._build_employee_message_entry(row, employee.employee_id) for row in rows]
