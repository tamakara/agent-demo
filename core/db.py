"""基于 SQLite 的会话与消息分区持久化实现。"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agent_state.db"
GLOBAL_LLM_CONFIG_KEY = "global_llm_config"
DEFAULT_LLM_MODEL = "agent-advoo"
DEFAULT_LLM_API_KEY = "sk-RtSmDDQfUbbrNczdVajJqoozIR8AYolUOWwSTgpc2s7rZq6F"
DEFAULT_LLM_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
DEFAULT_LLM_MAX_TOOL_ROUNDS = 6
DEFAULT_TOTAL_TOKEN_LIMIT = 200_000
LEGACY_DEFAULT_LLM_MODEL = "gpt-4o"
LEGACY_DEFAULT_LLM_API_KEY = ""
LEGACY_DEFAULT_LLM_BASE_URL = ""
LEGACY_DEFAULT_LLM_MAX_TOOL_ROUNDS = 6
LEGACY_DEFAULT_TOTAL_TOKEN_LIMIT = 200_000
GLOBAL_LLM_SELECT_SQL = """
SELECT
    llm_model,
    llm_api_key,
    llm_base_url,
    llm_max_tool_rounds,
    context_total_token_limit
FROM app_settings
WHERE setting_key = ?;
"""
TOUCH_SESSION_SQL = """
UPDATE sessions
SET updated_at = CURRENT_TIMESTAMP
WHERE session_id = ?;
"""


class SQLiteStore:
    """演示项目使用的 sqlite3 异步安全薄封装。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    def _ensure_conn(self) -> sqlite3.Connection:
        """确保连接已初始化。"""
        if self._conn is None:
            raise RuntimeError("数据库尚未初始化")
        return self._conn

    @staticmethod
    def _touch_session(conn: sqlite3.Connection, session_id: str) -> None:
        """刷新会话 updated_at，用于消息写入/删除后的会话排序。"""
        conn.execute(TOUCH_SESSION_SQL, (session_id,))

    @staticmethod
    def _fetch_global_llm_row(conn: sqlite3.Connection) -> sqlite3.Row | None:
        """读取 app_settings 中全局 LLM 配置行。"""
        return conn.execute(GLOBAL_LLM_SELECT_SQL, (GLOBAL_LLM_CONFIG_KEY,)).fetchone()

    async def initialize(self) -> None:
        async with self._lock:
            if self._conn is not None:
                return
            # data 目录在首次启动时按需创建，不要求仓库预置。
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    workbench_summary TEXT NOT NULL DEFAULT '',
                    is_flushing INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    llm_model TEXT NOT NULL DEFAULT '{DEFAULT_LLM_MODEL}',
                    llm_api_key TEXT NOT NULL DEFAULT '{DEFAULT_LLM_API_KEY}',
                    llm_base_url TEXT NOT NULL DEFAULT '{DEFAULT_LLM_BASE_URL}',
                    llm_max_tool_rounds INTEGER NOT NULL DEFAULT {DEFAULT_LLM_MAX_TOOL_ROUNDS},
                    context_total_token_limit INTEGER NOT NULL DEFAULT {DEFAULT_TOTAL_TOKEN_LIMIT},
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    zone TEXT NOT NULL,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_zone
                ON messages(session_id, zone, id);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages(session_id, id);
                """
            )
            self._ensure_global_llm_config_seed(conn)
            self._migrate_legacy_global_llm_config_defaults(conn)
            conn.commit()
            self._conn = conn

    @staticmethod
    def _ensure_global_llm_config_seed(conn: sqlite3.Connection) -> None:
        """初始化全局 LLM 配置默认值。"""
        existing = conn.execute(
            "SELECT 1 FROM app_settings WHERE setting_key = ?;",
            (GLOBAL_LLM_CONFIG_KEY,),
        ).fetchone()
        if existing is not None:
            return

        conn.execute(
            """
            INSERT INTO app_settings(
                setting_key,
                llm_model,
                llm_api_key,
                llm_base_url,
                llm_max_tool_rounds,
                context_total_token_limit
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                GLOBAL_LLM_CONFIG_KEY,
                DEFAULT_LLM_MODEL,
                DEFAULT_LLM_API_KEY,
                DEFAULT_LLM_BASE_URL,
                DEFAULT_LLM_MAX_TOOL_ROUNDS,
                DEFAULT_TOTAL_TOKEN_LIMIT,
            ),
        )

    @staticmethod
    def _migrate_legacy_global_llm_config_defaults(conn: sqlite3.Connection) -> None:
        """
        将“历史空配置默认值”升级为当前预置默认值。

        仅当配置仍是旧版初始状态（gpt-4o + 空 key/base_url + 默认轮次/窗口）时升级，
        避免覆盖用户已经手动保存过的自定义配置。
        """
        row = SQLiteStore._fetch_global_llm_row(conn)
        if row is None:
            return

        model = str(row["llm_model"] or "").strip()
        api_key = str(row["llm_api_key"] or "").strip()
        base_url = str(row["llm_base_url"] or "").strip()
        max_tool_rounds = int(row["llm_max_tool_rounds"] or 0)
        total_token_limit = int(row["context_total_token_limit"] or 0)

        is_legacy_default = (
            model == LEGACY_DEFAULT_LLM_MODEL
            and api_key == LEGACY_DEFAULT_LLM_API_KEY
            and base_url == LEGACY_DEFAULT_LLM_BASE_URL
            and max_tool_rounds == LEGACY_DEFAULT_LLM_MAX_TOOL_ROUNDS
            and total_token_limit == LEGACY_DEFAULT_TOTAL_TOKEN_LIMIT
        )
        if not is_legacy_default:
            return

        conn.execute(
            """
            UPDATE app_settings
            SET
                llm_model = ?,
                llm_api_key = ?,
                llm_base_url = ?,
                llm_max_tool_rounds = ?,
                context_total_token_limit = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE setting_key = ?;
            """,
            (
                DEFAULT_LLM_MODEL,
                DEFAULT_LLM_API_KEY,
                DEFAULT_LLM_BASE_URL,
                DEFAULT_LLM_MAX_TOOL_ROUNDS,
                DEFAULT_TOTAL_TOKEN_LIMIT,
                GLOBAL_LLM_CONFIG_KEY,
            ),
        )

    async def close(self) -> None:
        async with self._lock:
            if self._conn is None:
                return
            self._conn.close()
            self._conn = None

    async def ensure_session(self, session_id: str) -> None:
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                INSERT INTO sessions(session_id) VALUES (?)
                ON CONFLICT(session_id) DO NOTHING;
                """,
                (session_id,),
            )
            conn.commit()

    async def create_session(self, session_id: str) -> dict[str, Any]:
        await self.ensure_session(session_id)
        return await self.get_session(session_id)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            row = conn.execute(
                """
                SELECT
                    session_id,
                    workbench_summary,
                    is_flushing,
                    created_at,
                    updated_at
                FROM sessions
                WHERE session_id = ?;
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError(f"会话不存在：{session_id}")
            return {
                "session_id": row["session_id"],
                "workbench_summary": row["workbench_summary"] or "",
                "is_flushing": bool(row["is_flushing"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    async def get_global_llm_config(self) -> dict[str, Any]:
        async with self._lock:
            conn = self._ensure_conn()
            row = self._fetch_global_llm_row(conn)
            if row is None:
                self._ensure_global_llm_config_seed(conn)
                conn.commit()
                row = self._fetch_global_llm_row(conn)
            if row is None:
                raise RuntimeError("全局 LLM 配置初始化失败")
            model = str(row["llm_model"] or "").strip() or DEFAULT_LLM_MODEL
            api_key = str(row["llm_api_key"] or "").strip() or DEFAULT_LLM_API_KEY
            base_url = str(row["llm_base_url"] or "").strip() or DEFAULT_LLM_BASE_URL
            return {
                "model": model,
                "api_key": api_key,
                "base_url": base_url,
                "max_tool_rounds": int(row["llm_max_tool_rounds"] or DEFAULT_LLM_MAX_TOOL_ROUNDS),
                "total_token_limit": int(row["context_total_token_limit"] or DEFAULT_TOTAL_TOKEN_LIMIT),
            }

    async def update_global_llm_config(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None,
        max_tool_rounds: int,
        total_token_limit: int,
    ) -> None:
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                INSERT INTO app_settings(
                    setting_key,
                    llm_model,
                    llm_api_key,
                    llm_base_url,
                    llm_max_tool_rounds,
                    context_total_token_limit,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key) DO UPDATE SET
                    llm_model = excluded.llm_model,
                    llm_api_key = excluded.llm_api_key,
                    llm_base_url = excluded.llm_base_url,
                    llm_max_tool_rounds = excluded.llm_max_tool_rounds,
                    context_total_token_limit = excluded.context_total_token_limit,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (
                    GLOBAL_LLM_CONFIG_KEY,
                    model,
                    api_key,
                    base_url or "",
                    int(max_tool_rounds),
                    int(total_token_limit),
                ),
            )
            conn.commit()

    async def set_is_flushing(self, session_id: str, value: bool) -> None:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET is_flushing = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?;
                """,
                (1 if value else 0, session_id),
            )
            conn.commit()

    async def update_workbench_summary(self, session_id: str, summary: str) -> None:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                """
                UPDATE sessions
                SET workbench_summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?;
                """,
                (summary, session_id),
            )
            conn.commit()

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        zone: str,
        token_count: int,
    ) -> int:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            cursor = conn.execute(
                """
                INSERT INTO messages(session_id, role, content, zone, token_count)
                VALUES (?, ?, ?, ?, ?);
                """,
                (session_id, role, content, zone, token_count),
            )
            self._touch_session(conn, session_id)
            conn.commit()
            return int(cursor.lastrowid)

    async def list_messages(
        self,
        session_id: str,
        *,
        zones: Sequence[str] | None = None,
        roles: Sequence[str] | None = None,
        ascending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        await self.ensure_session(session_id)
        query = (
            "SELECT id, session_id, role, content, zone, token_count, created_at "
            "FROM messages WHERE session_id = ?"
        )
        params: list[Any] = [session_id]

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

    async def sum_tokens_by_zone(self, session_id: str) -> dict[str, int]:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                """
                SELECT zone, COALESCE(SUM(token_count), 0) AS total_tokens
                FROM messages
                WHERE session_id = ?
                GROUP BY zone;
                """,
                (session_id,),
            ).fetchall()
            result = {str(row["zone"]): int(row["total_tokens"]) for row in rows}
            return result

    async def clear_messages(self, session_id: str) -> None:
        await self.ensure_session(session_id)
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))
            self._touch_session(conn, session_id)
            conn.commit()

    async def delete_messages_by_zones(self, session_id: str, zones: Iterable[str]) -> None:
        await self.ensure_session(session_id)
        zones = list(zones)
        if not zones:
            return
        placeholders = ",".join(["?"] * len(zones))
        params = [session_id, *zones]
        async with self._lock:
            conn = self._ensure_conn()
            conn.execute(
                f"DELETE FROM messages WHERE session_id = ? AND zone IN ({placeholders});",
                tuple(params),
            )
            self._touch_session(conn, session_id)
            conn.commit()

    async def list_sessions(self, *, limit: int = 200) -> list[dict[str, Any]]:
        async with self._lock:
            conn = self._ensure_conn()
            rows = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.is_flushing,
                    s.created_at,
                    s.updated_at,
                    COALESCE(COUNT(m.id), 0) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON s.session_id = m.session_id
                GROUP BY s.session_id, s.is_flushing, s.created_at, s.updated_at
                ORDER BY s.updated_at DESC, s.created_at DESC
                LIMIT ?;
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
