"""SQLite 仓储实现与数据访问逻辑。"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.interfaces import IMessageRepository, ISettingsRepository, ISessionRepository
from app.memory_specs import (
    DEFAULT_DIALOGUE_SUMMARY_RATIO,
    DEFAULT_MEMORY_CAPACITY_RATIO,
    DEFAULT_NOTEBOOK_CAPACITY_RATIO,
)
from app.window_policy import DEFAULT_RETENTION_RATIO, DEFAULT_TOTAL_LIMIT
from domain.models import GlobalSettings


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "agent_state.db"
DEFAULT_LLM_MODEL = "agent-advoo"
DEFAULT_LLM_API_KEY = "sk-RtSmDDQfUbbrNczdVajJqoozIR8AYolUOWwSTgpc2s7rZq6F"
DEFAULT_LLM_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
DEFAULT_LLM_MAX_TOOL_ROUNDS = 64
DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"
DEFAULT_DEEP_THINKING_ENABLED = 0
DEFAULT_MEMORY_CAPACITY_RATIO_SQL = DEFAULT_MEMORY_CAPACITY_RATIO
DEFAULT_NOTEBOOK_CAPACITY_RATIO_SQL = DEFAULT_NOTEBOOK_CAPACITY_RATIO
DEFAULT_DIALOGUE_SUMMARY_RATIO_SQL = DEFAULT_DIALOGUE_SUMMARY_RATIO
DEFAULT_RETENTION_RATIO_SQL = DEFAULT_RETENTION_RATIO
GLOBAL_LLM_SELECT_SQL = """
SELECT
    llm_model,
    llm_api_key,
    llm_base_url,
    llm_max_tool_rounds,
    context_total_token_limit,
    tokenizer_model,
    memory_capacity_ratio,
    notebook_capacity_ratio,
    dialogue_summary_ratio,
    retention_ratio,
    deep_thinking_enabled
FROM app_settings
WHERE user_id = ?;
"""
TOUCH_SESSION_SQL = """
UPDATE sessions
SET updated_at = CURRENT_TIMESTAMP
WHERE user_id = ? AND session_id = ?;
"""


class SQLiteRepository(ISessionRepository, IMessageRepository, ISettingsRepository):
    """SQLite 的仓储适配器。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        """初始化数据库路径与连接状态。"""
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    def _ensure_conn(self) -> sqlite3.Connection:
        """返回已初始化连接；若未初始化则抛错。"""
        if self._conn is None:
            raise RuntimeError("数据库尚未初始化")
        return self._conn

    @staticmethod
    def _touch_session(conn: sqlite3.Connection, user_id: str, session_id: str) -> None:
        """更新会话 ``updated_at``，用于会话排序。"""
        conn.execute(TOUCH_SESSION_SQL, (user_id, session_id))

    @staticmethod
    def _fetch_global_llm_row(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
        """读取用户全局 LLM 配置行。"""
        return conn.execute(GLOBAL_LLM_SELECT_SQL, (user_id,)).fetchone()

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
        return {str(row["name"]).strip() for row in rows if str(row["name"]).strip()}

    @classmethod
    def _ensure_app_settings_columns(cls, conn: sqlite3.Connection) -> None:
        columns = cls._table_columns(conn, "app_settings")
        if "memory_capacity_ratio" not in columns:
            conn.execute(
                (
                    "ALTER TABLE app_settings "
                    f"ADD COLUMN memory_capacity_ratio REAL NOT NULL DEFAULT {DEFAULT_MEMORY_CAPACITY_RATIO_SQL};"
                )
            )
        if "notebook_capacity_ratio" not in columns:
            conn.execute(
                (
                    "ALTER TABLE app_settings "
                    f"ADD COLUMN notebook_capacity_ratio REAL NOT NULL DEFAULT {DEFAULT_NOTEBOOK_CAPACITY_RATIO_SQL};"
                )
            )
        if "dialogue_summary_ratio" not in columns:
            conn.execute(
                (
                    "ALTER TABLE app_settings "
                    f"ADD COLUMN dialogue_summary_ratio REAL NOT NULL DEFAULT {DEFAULT_DIALOGUE_SUMMARY_RATIO_SQL};"
                )
            )
        if "retention_ratio" not in columns:
            conn.execute(
                (
                    "ALTER TABLE app_settings "
                    f"ADD COLUMN retention_ratio REAL NOT NULL DEFAULT {DEFAULT_RETENTION_RATIO_SQL};"
                )
            )

    async def initialize(self) -> None:
        """初始化 SQLite 连接并确保表结构存在。"""
        async with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # 使用 WAL 提高并发读写能力，并显式开启外键约束。
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    workbench_summary TEXT NOT NULL DEFAULT '',
                    is_compressing INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(user_id, session_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    user_id TEXT PRIMARY KEY,
                    llm_model TEXT NOT NULL,
                    llm_api_key TEXT NOT NULL,
                    llm_base_url TEXT NOT NULL,
                    llm_max_tool_rounds INTEGER NOT NULL,
                    context_total_token_limit INTEGER NOT NULL,
                    tokenizer_model TEXT NOT NULL DEFAULT 'kimi-k2.5',
                    memory_capacity_ratio REAL NOT NULL DEFAULT 0.10,
                    notebook_capacity_ratio REAL NOT NULL DEFAULT 0.04,
                    dialogue_summary_ratio REAL NOT NULL DEFAULT 0.05,
                    retention_ratio REAL NOT NULL DEFAULT 0.10,
                    deep_thinking_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    message_kind TEXT NOT NULL DEFAULT 'chat',
                    content TEXT NOT NULL,
                    zone TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id, session_id)
                        REFERENCES sessions(user_id, session_id)
                        ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_user_session_zone
                ON messages(user_id, session_id, zone, id);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_user_session_zone_kind
                ON messages(user_id, session_id, zone, message_kind, id);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_user_session_id
                ON messages(user_id, session_id, id);
                """
            )
            self._ensure_app_settings_columns(conn)
            conn.commit()
            self._conn = conn

    @staticmethod
    def _ensure_global_llm_config_seed(conn: sqlite3.Connection, user_id: str) -> None:
        """在配置缺失时插入默认 LLM 参数。"""
        existing = conn.execute(
            "SELECT 1 FROM app_settings WHERE user_id = ?;",
            (user_id,),
        ).fetchone()
        if existing is not None:
            return

        conn.execute(
            """
            INSERT INTO app_settings(
                user_id,
                llm_model,
                llm_api_key,
                llm_base_url,
                llm_max_tool_rounds,
                context_total_token_limit,
                tokenizer_model,
                memory_capacity_ratio,
                notebook_capacity_ratio,
                dialogue_summary_ratio,
                retention_ratio,
                deep_thinking_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                user_id,
                DEFAULT_LLM_MODEL,
                DEFAULT_LLM_API_KEY,
                DEFAULT_LLM_BASE_URL,
                DEFAULT_LLM_MAX_TOOL_ROUNDS,
                DEFAULT_TOTAL_LIMIT,
                DEFAULT_TOKENIZER_MODEL,
                DEFAULT_MEMORY_CAPACITY_RATIO_SQL,
                DEFAULT_NOTEBOOK_CAPACITY_RATIO_SQL,
                DEFAULT_DIALOGUE_SUMMARY_RATIO_SQL,
                DEFAULT_RETENTION_RATIO_SQL,
                DEFAULT_DEEP_THINKING_ENABLED,
            ),
        )

    async def close(self) -> None:
        """关闭数据库连接。"""
        async with self._lock:
            if self._conn is None:
                return
            self._conn.close()
            self._conn = None

    async def ensure_session(self, user_id: str, session_id: str) -> None:
        """确保会话存在，不存在则创建。"""
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                INSERT INTO sessions(user_id, session_id) VALUES (?, ?)
                ON CONFLICT(user_id, session_id) DO NOTHING;
                """,
                (user_id, session_id),
            )
            conn.commit()

    async def create_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        """创建会话并返回会话对象。"""
        await self.ensure_session(user_id, session_id)
        return await self.get_session(user_id, session_id)

    async def get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        """读取会话对象。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                """
                SELECT
                    user_id,
                    session_id,
                    workbench_summary,
                    is_compressing,
                    created_at,
                    updated_at
                FROM sessions
                WHERE user_id = ? AND session_id = ?;
                """,
                (user_id, session_id),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"会话不存在：{user_id}/{session_id}")
            return {
                "user_id": row["user_id"],
                "session_id": row["session_id"],
                "workbench_summary": str(row["workbench_summary"] or ""),
                "is_compressing": bool(row["is_compressing"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    async def get_global_settings(self, user_id: str) -> GlobalSettings:
        """读取用户全局设置；缺失时自动补种默认值。"""
        async with self._lock:
            conn = self._ensure_conn()
            row = self._fetch_global_llm_row(conn, user_id)
            if row is None:
                self._ensure_global_llm_config_seed(conn, user_id)
                conn.commit()
                row = self._fetch_global_llm_row(conn, user_id)
            if row is None:
                raise RuntimeError(f"用户配置初始化失败：{user_id}")
            model = str(row["llm_model"] or "").strip() or DEFAULT_LLM_MODEL
            api_key = str(row["llm_api_key"] or "").strip() or DEFAULT_LLM_API_KEY
            base_url = str(row["llm_base_url"] or "").strip() or DEFAULT_LLM_BASE_URL
            return GlobalSettings(
                user_id=user_id,
                model=model,
                api_key=api_key,
                base_url=base_url,
                max_tool_rounds=int(row["llm_max_tool_rounds"] or DEFAULT_LLM_MAX_TOOL_ROUNDS),
                total_token_limit=int(row["context_total_token_limit"] or DEFAULT_TOTAL_LIMIT),
                tokenizer_model=str(row["tokenizer_model"] or "").strip() or DEFAULT_TOKENIZER_MODEL,
                memory_capacity_ratio=float(
                    row["memory_capacity_ratio"] if row["memory_capacity_ratio"] is not None else DEFAULT_MEMORY_CAPACITY_RATIO_SQL
                ),
                notebook_capacity_ratio=float(
                    row["notebook_capacity_ratio"]
                    if row["notebook_capacity_ratio"] is not None
                    else DEFAULT_NOTEBOOK_CAPACITY_RATIO_SQL
                ),
                dialogue_summary_ratio=float(
                    row["dialogue_summary_ratio"]
                    if row["dialogue_summary_ratio"] is not None
                    else DEFAULT_DIALOGUE_SUMMARY_RATIO_SQL
                ),
                retention_ratio=float(
                    row["retention_ratio"] if row["retention_ratio"] is not None else DEFAULT_RETENTION_RATIO_SQL
                ),
                deep_thinking_enabled=bool(int(row["deep_thinking_enabled"] or 0)),
            )

    async def update_global_settings(self, settings: GlobalSettings) -> GlobalSettings:
        """写入用户全局设置并返回最新结果。"""
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                INSERT INTO app_settings(
                    user_id,
                    llm_model,
                    llm_api_key,
                    llm_base_url,
                    llm_max_tool_rounds,
                    context_total_token_limit,
                    tokenizer_model,
                    memory_capacity_ratio,
                    notebook_capacity_ratio,
                    dialogue_summary_ratio,
                    retention_ratio,
                    deep_thinking_enabled,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    llm_model = excluded.llm_model,
                    llm_api_key = excluded.llm_api_key,
                    llm_base_url = excluded.llm_base_url,
                    llm_max_tool_rounds = excluded.llm_max_tool_rounds,
                    context_total_token_limit = excluded.context_total_token_limit,
                    tokenizer_model = excluded.tokenizer_model,
                    memory_capacity_ratio = excluded.memory_capacity_ratio,
                    notebook_capacity_ratio = excluded.notebook_capacity_ratio,
                    dialogue_summary_ratio = excluded.dialogue_summary_ratio,
                    retention_ratio = excluded.retention_ratio,
                    deep_thinking_enabled = excluded.deep_thinking_enabled,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    settings.user_id,
                    settings.model,
                    settings.api_key,
                    settings.base_url or "",
                    int(settings.max_tool_rounds),
                    int(settings.total_token_limit),
                    settings.tokenizer_model,
                    float(settings.memory_capacity_ratio),
                    float(settings.notebook_capacity_ratio),
                    float(settings.dialogue_summary_ratio),
                    float(settings.retention_ratio),
                    1 if settings.deep_thinking_enabled else 0,
                ),
            )
            conn.commit()
        return await self.get_global_settings(settings.user_id)

    async def set_is_compressing(self, user_id: str, session_id: str, value: bool) -> None:
        """更新会话 ``is_compressing`` 状态。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET is_compressing = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND session_id = ?;
                """,
                (1 if value else 0, user_id, session_id),
            )
            conn.commit()

    async def set_workbench_summary(self, user_id: str, session_id: str, summary: str) -> None:
        """覆盖更新会话 ``workbench_summary``。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET workbench_summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND session_id = ?;
                """,
                (str(summary or ""), user_id, session_id),
            )
            conn.commit()

    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        message_kind: str,
        content: str,
        zone: str,
        token_count: int,
    ) -> int:
        """写入一条消息并返回新消息 ID。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            cursor = conn.execute(
                """
                INSERT INTO messages(user_id, session_id, role, message_kind, content, zone, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (user_id, session_id, role, message_kind, content, zone, token_count),
            )
            self._touch_session(conn, user_id, session_id)
            conn.commit()
            return int(cursor.lastrowid)

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        zones: Sequence[str] | None = None,
        roles: Sequence[str] | None = None,
        message_kinds: Sequence[str] | None = None,
        ascending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按过滤条件查询消息列表。"""
        await self.ensure_session(user_id, session_id)
        query = (
            "SELECT id, user_id, session_id, role, message_kind, content, zone, token_count, created_at "
            "FROM messages WHERE user_id = ? AND session_id = ?"
        )
        params: list[Any] = [user_id, session_id]

        # 通过参数化占位符拼接 IN 子句，避免 SQL 注入并支持动态过滤。
        if zones:
            placeholders = ",".join(["?"] * len(zones))
            query += f" AND zone IN ({placeholders})"
            params.extend(zones)
        if roles:
            placeholders = ",".join(["?"] * len(roles))
            query += f" AND role IN ({placeholders})"
            params.extend(roles)
        if message_kinds:
            placeholders = ",".join(["?"] * len(message_kinds))
            query += f" AND message_kind IN ({placeholders})"
            params.extend(message_kinds)

        query += " ORDER BY id " + ("ASC" if ascending else "DESC")
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        query += ";"

        async with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    async def sum_tokens_by_zone(self, user_id: str, session_id: str) -> dict[str, int]:
        """按生命周期分区汇总 token 消耗。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                """
                SELECT zone, COALESCE(SUM(token_count), 0) AS total_tokens
                FROM messages
                WHERE user_id = ? AND session_id = ?
                GROUP BY zone;
                """,
                (user_id, session_id),
            ).fetchall()
            return {str(row["zone"]): int(row["total_tokens"]) for row in rows}

    async def clear_messages(self, user_id: str, session_id: str) -> None:
        """清空指定会话的所有消息。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                "DELETE FROM messages WHERE user_id = ? AND session_id = ?;",
                (user_id, session_id),
            )
            self._touch_session(conn, user_id, session_id)
            conn.commit()

    async def delete_messages_by_zones(self, user_id: str, session_id: str, zones: Iterable[str]) -> None:
        """按分区删除消息。"""
        await self.ensure_session(user_id, session_id)
        zones = list(zones)
        if not zones:
            return
        placeholders = ",".join(["?"] * len(zones))
        params = [user_id, session_id, *zones]
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                f"DELETE FROM messages WHERE user_id = ? AND session_id = ? AND zone IN ({placeholders});",
                tuple(params),
            )
            self._touch_session(conn, user_id, session_id)
            conn.commit()

    async def list_sessions(self, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """查询用户会话列表并附带消息总数。"""
        async with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                """
                SELECT
                    s.user_id,
                    s.session_id,
                    s.is_compressing,
                    s.created_at,
                    s.updated_at,
                    COALESCE(COUNT(m.id), 0) AS message_count
                FROM sessions s
                LEFT JOIN messages m
                    ON s.user_id = m.user_id
                    AND s.session_id = m.session_id
                WHERE s.user_id = ?
                GROUP BY s.user_id, s.session_id, s.is_compressing, s.created_at, s.updated_at
                ORDER BY s.updated_at DESC, s.created_at DESC
                LIMIT ?;
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    async def delete_session(self, user_id: str, session_id: str) -> None:
        """删除指定会话。"""
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND session_id = ?;",
                (user_id, session_id),
            )
            conn.commit()

