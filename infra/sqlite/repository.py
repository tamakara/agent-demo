"""SQLite 仓储实现与数据访问逻辑。"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.ports.repositories import MessageRepositoryPort, SessionRepositoryPort, UserSettingsRepositoryPort
from domain.models import GlobalSettings
from domain.window_policy import DEFAULT_TOTAL_LIMIT


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "agent_state.db"
DEFAULT_LLM_MODEL = "agent-advoo"
DEFAULT_LLM_API_KEY = "sk-RtSmDDQfUbbrNczdVajJqoozIR8AYolUOWwSTgpc2s7rZq6F"
DEFAULT_LLM_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
DEFAULT_LLM_MAX_TOOL_ROUNDS = 64
DEFAULT_TOKENIZER_MODEL = "kimi-k2.5"
GLOBAL_LLM_SELECT_SQL = """
SELECT
    llm_model,
    llm_api_key,
    llm_base_url,
    llm_max_tool_rounds,
    context_total_token_limit,
    tokenizer_model
FROM app_settings
WHERE user_id = ?;
"""
TOUCH_SESSION_SQL = """
UPDATE sessions
SET updated_at = CURRENT_TIMESTAMP
WHERE user_id = ? AND session_id = ?;
"""


class SQLiteRepository(SessionRepositoryPort, MessageRepositoryPort, UserSettingsRepositoryPort):
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
                    is_flushing INTEGER NOT NULL DEFAULT 0,
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
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._ensure_app_settings_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
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
                CREATE INDEX IF NOT EXISTS idx_messages_user_session_id
                ON messages(user_id, session_id, id);
                """
            )
            conn.commit()
            self._conn = conn

    @staticmethod
    def _ensure_app_settings_schema(conn: sqlite3.Connection) -> None:
        """确保 ``app_settings`` 表包含当前版本所需列。"""
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(app_settings);").fetchall()
            if row["name"] is not None
        }
        if "tokenizer_model" not in columns:
            conn.execute(
                """
                ALTER TABLE app_settings
                ADD COLUMN tokenizer_model TEXT NOT NULL DEFAULT 'kimi-k2.5';
                """
            )
        conn.execute(
            """
            UPDATE app_settings
            SET tokenizer_model = ?
            WHERE tokenizer_model IS NULL
                OR TRIM(tokenizer_model) = ''
                OR LOWER(TRIM(tokenizer_model)) <> ?;
            """,
            (DEFAULT_TOKENIZER_MODEL, DEFAULT_TOKENIZER_MODEL),
        )

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
                tokenizer_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                user_id,
                DEFAULT_LLM_MODEL,
                DEFAULT_LLM_API_KEY,
                DEFAULT_LLM_BASE_URL,
                DEFAULT_LLM_MAX_TOOL_ROUNDS,
                DEFAULT_TOTAL_LIMIT,
                DEFAULT_TOKENIZER_MODEL,
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
                    is_flushing,
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
                "workbench_summary": row["workbench_summary"] or "",
                "is_flushing": bool(row["is_flushing"]),
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
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    llm_model = excluded.llm_model,
                    llm_api_key = excluded.llm_api_key,
                    llm_base_url = excluded.llm_base_url,
                    llm_max_tool_rounds = excluded.llm_max_tool_rounds,
                    context_total_token_limit = excluded.context_total_token_limit,
                    tokenizer_model = excluded.tokenizer_model,
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
                ),
            )
            conn.commit()
        return await self.get_global_settings(settings.user_id)

    async def set_is_flushing(self, user_id: str, session_id: str, value: bool) -> None:
        """更新会话 ``is_flushing`` 状态。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET is_flushing = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND session_id = ?;
                """,
                (1 if value else 0, user_id, session_id),
            )
            conn.commit()

    async def update_workbench_summary(self, user_id: str, session_id: str, summary: str) -> None:
        """更新会话的工作台摘要文本。"""
        await self.ensure_session(user_id, session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET workbench_summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND session_id = ?;
                """,
                (summary, user_id, session_id),
            )
            conn.commit()

    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
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
                INSERT INTO messages(user_id, session_id, role, content, zone, token_count)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (user_id, session_id, role, content, zone, token_count),
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
        ascending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按过滤条件查询消息列表。"""
        await self.ensure_session(user_id, session_id)
        query = (
            "SELECT id, user_id, session_id, role, content, zone, token_count, created_at "
            "FROM messages WHERE user_id = ? AND session_id = ?"
        )
        params: list[Any] = [user_id, session_id]

        # 通过参数化占位符拼接 IN 子句，避免 SQL 注入并兼容动态过滤。
        if zones:
            placeholders = ",".join(["?"] * len(zones))
            query += f" AND zone IN ({placeholders})"
            params.extend(zones)
        if roles:
            placeholders = ",".join(["?"] * len(roles))
            query += f" AND role IN ({placeholders})"
            params.extend(roles)

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
        """按分区汇总 token 消耗。"""
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
                    s.is_flushing,
                    s.created_at,
                    s.updated_at,
                    COALESCE(COUNT(m.id), 0) AS message_count
                FROM sessions s
                LEFT JOIN messages m
                    ON s.user_id = m.user_id
                    AND s.session_id = m.session_id
                WHERE s.user_id = ?
                GROUP BY s.user_id, s.session_id, s.is_flushing, s.created_at, s.updated_at
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
