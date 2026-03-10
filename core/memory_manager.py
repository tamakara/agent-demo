"""上下文窗口分区、token 统计与异步刷盘流程。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

import tiktoken

from core.agent import AgentRunResult, EventCallback, run_agent_with_tools
from core.db import SQLiteStore
from core.models import LLMConfig, MemoryStatusResponse
from core.tools import (
    ASSET_PLACEHOLDER_FILE,
    SYSTEM_PROMPT_FILE,
    TOOL_SCHEMAS,
    list_memory_file_names,
    read_memory_file_impl,
)


DEFAULT_TOTAL_LIMIT = 200_000
MIN_TOTAL_LIMIT = 20_000

SYSTEM_PROMPT_PERCENT = 10
SUMMARY_PERCENT = 1
RECENT_RAW_PERCENT = 9

ARCHIVE_SYSTEM_PROMPT = (
    "你是一个记忆整理专员。请分析给定对话记录，并在必要时调用 "
    "`write_memory_file` 工具，将新设定追加到最合适的记忆文件中。"
    "整理完成后，请输出纯文本“工作台摘要”，用于后续常驻区快速加载。"
)


@dataclass(slots=True, frozen=True)
class WindowThresholds:
    """会话窗口预算配置（按 total_limit 动态计算）。"""

    total_limit: int
    system_prompt_limit: int
    summary_limit: int
    recent_raw_limit: int
    recent_total_limit: int
    resident_limit: int
    dialogue_limit: int
    flush_trigger: int

    @classmethod
    def from_total_limit(cls, total_limit: int) -> WindowThresholds:
        normalized = max(MIN_TOTAL_LIMIT, int(total_limit))
        system_prompt_limit = max(1, (normalized * SYSTEM_PROMPT_PERCENT) // 100)
        summary_limit = max(1, (normalized * SUMMARY_PERCENT) // 100)
        recent_raw_limit = max(1, (normalized * RECENT_RAW_PERCENT) // 100)
        recent_total_limit = summary_limit + recent_raw_limit
        resident_limit = system_prompt_limit + recent_total_limit
        dialogue_limit = max(1, normalized - resident_limit)
        return cls(
            total_limit=normalized,
            system_prompt_limit=system_prompt_limit,
            summary_limit=summary_limit,
            recent_raw_limit=recent_raw_limit,
            recent_total_limit=recent_total_limit,
            resident_limit=resident_limit,
            dialogue_limit=dialogue_limit,
            flush_trigger=normalized,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "system_prompt_limit": self.system_prompt_limit,
            "summary_limit": self.summary_limit,
            "recent_raw_limit": self.recent_raw_limit,
            "recent_total_limit": self.recent_total_limit,
            "resident_limit": self.resident_limit,
            "dialogue_limit": self.dialogue_limit,
            "total_limit": self.total_limit,
            "flush_trigger": self.flush_trigger,
        }


@dataclass(slots=True)
class ChatProcessResult:
    """单次聊天处理返回值（供 API 层组装 SSE 使用）。"""

    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    status: MemoryStatusResponse
    flush_scheduled: bool


class MemoryManager:
    """管理会话级记忆分区与刷盘生命周期。"""

    def __init__(self, db: SQLiteStore) -> None:
        self.db = db
        self._session_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _get_session_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """按 (user_id, session_id) 维度提供串行锁，避免并发写同一会话。"""
        lock_key = (user_id, session_id)
        async with self._locks_guard:
            if lock_key not in self._session_locks:
                self._session_locks[lock_key] = asyncio.Lock()
            return self._session_locks[lock_key]

    @staticmethod
    def _encoding_for_model(model: str) -> tiktoken.Encoding:
        """按模型名返回编码器；未知模型回退到 cl100k_base。"""
        try:
            return tiktoken.encoding_for_model(model)
        except Exception:  # noqa: BLE001
            return tiktoken.get_encoding("cl100k_base")

    @classmethod
    def _count_tokens(cls, text: str, model: str) -> int:
        """按模型编码器统计 token。"""
        normalized = text or ""
        encoding = cls._encoding_for_model(model)
        return len(encoding.encode(normalized))

    @classmethod
    def _truncate_text_to_tokens(cls, text: str, limit: int, model: str) -> str:
        """
        将文本截断到指定 token 上限内。
        limit <= 0 时返回空字符串。
        """
        if limit <= 0:
            return ""
        normalized = text or ""
        encoding = cls._encoding_for_model(model)
        encoded = encoding.encode(normalized)
        if len(encoded) <= limit:
            return normalized
        return encoding.decode(encoded[:limit]).rstrip()

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict[str, Any] | None:
        """把字符串解析为 JSON 对象；非对象时返回 None。"""
        try:
            parsed = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    @staticmethod
    def _to_json_string(value: Any, *, default: str = "{}") -> str:
        """把任意值转换为 JSON 字符串或文本字符串。"""
        if value is None:
            return default
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _to_tool_content(value: Any) -> str:
        """把工具结果对象转换成 OpenAI tool 消息 content。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if "result" in value and len(value) == 1:
                return str(value.get("result", ""))
            if "error" in value and len(value) == 1:
                return str(value.get("error", ""))
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _normalize_prompt_role(raw_role: Any) -> str:
        """规范化消息 role；未知角色回退 assistant。"""
        role = str(raw_role).strip()
        if role in {"system", "user", "assistant", "tool"}:
            return role
        return "assistant"

    @staticmethod
    def _row_token_count(row: dict[str, Any], model: str) -> int:
        """优先使用落库 token_count；缺失时按内容即时估算。"""
        raw = row.get("token_count", 0)
        try:
            parsed = int(raw)
        except Exception:  # noqa: BLE001
            parsed = 0
        if parsed > 0:
            return parsed
        return MemoryManager._count_tokens(str(row.get("content", "")), model)

    @staticmethod
    def _extract_markdown_section(markdown: str, section_title: str) -> str:
        """按二级标题提取指定章节正文，不存在时返回空字符串。"""
        pattern = re.compile(
            rf"(?ms)^##\s*{re.escape(section_title)}\s*$\n(.*?)(?=^##\s|\Z)",
        )
        matched = pattern.search(markdown or "")
        if not matched:
            return ""
        return matched.group(1).strip()

    def _split_system_prompt_sections(self, markdown: str) -> tuple[str, str]:
        """解析系统提示词中的“规则/工具定义”两个分区。"""
        normalized = (markdown or "").strip()
        if not normalized:
            return "", ""

        rules = self._extract_markdown_section(normalized, "规则")
        tool_defs = self._extract_markdown_section(normalized, "工具定义")
        return rules, tool_defs

    @staticmethod
    def _render_tool_definitions_from_schema() -> str:
        """从 TOOL_SCHEMAS 生成可读 Markdown，作为工具定义兜底内容。"""
        lines: list[str] = []
        for schema in TOOL_SCHEMAS:
            function_spec = schema.get("function", {})
            if not isinstance(function_spec, dict):
                continue

            name = str(function_spec.get("name", "")).strip() or "unknown_tool"
            desc = str(function_spec.get("description", "")).strip() or "无描述"
            parameters = function_spec.get("parameters", {})
            required_fields: list[str] = []
            if isinstance(parameters, dict):
                raw_required = parameters.get("required", [])
                if isinstance(raw_required, list):
                    required_fields = [str(field).strip() for field in raw_required if str(field).strip()]

            required_text = "、".join(required_fields) if required_fields else "无"
            lines.append(f"- `{name}`：{desc}（必填参数：{required_text}）")
        return "\n".join(lines).strip()

    @staticmethod
    def _system_preamble(thresholds: WindowThresholds) -> str:
        """按当前预算配置生成系统前导说明。"""
        return (
            f"你正在运行于 {thresholds.total_limit} token 上下文窗口。\n"
            f"- 系统提示词与记忆文件：上限 {thresholds.system_prompt_limit} token（10%）。\n"
            f"- 最近对话：上限 {thresholds.recent_total_limit} token（10%），"
            f"其中摘要 {thresholds.summary_limit} token（1%），"
            f"原始对话 {thresholds.recent_raw_limit} token（9%）。\n"
            f"- 对话区（含工具/缓冲）：上限 {thresholds.dialogue_limit} token（约 80%）。\n"
            "- 请优先复用已有记忆，并在必要时调用工具更新记忆。"
        )

    @classmethod
    def _fit_section_to_budget(
        cls,
        *,
        section_title: str,
        content: str,
        token_budget: int,
        model: str,
    ) -> str:
        """将“标题 + 正文”整体控制在指定 token 预算内。"""
        if token_budget <= 0:
            return ""

        header = f"## {section_title}\n"
        header_tokens = cls._count_tokens(header, model)
        content_budget = max(0, token_budget - header_tokens)
        clipped = cls._truncate_text_to_tokens(content.strip(), content_budget, model)

        if not clipped and content_budget > 0:
            clipped = cls._truncate_text_to_tokens("(暂无内容)", content_budget, model)

        return f"{header}{clipped}".strip()

    @classmethod
    def _take_latest_rows_by_token_budget(
        cls,
        *,
        rows_ascending: list[dict[str, Any]],
        token_budget: int,
        model: str,
    ) -> list[dict[str, Any]]:
        """
        从“时间升序”消息中取最新尾部片段，保证总 token 不超过预算。

        一旦继续向前追加会超预算，就停止追加更早消息，以保持尾部连续性。
        """
        if token_budget <= 0 or not rows_ascending:
            return []

        selected_reversed: list[dict[str, Any]] = []
        used_tokens = 0

        for row in reversed(rows_ascending):
            row_tokens = cls._row_token_count(row, model)
            if used_tokens + row_tokens > token_budget:
                break
            selected_reversed.append(row)
            used_tokens += row_tokens

        return list(reversed(selected_reversed))

    @classmethod
    def _take_latest_rows_from_desc_by_budget(
        cls,
        *,
        rows_descending: list[dict[str, Any]],
        token_budget: int,
        model: str,
    ) -> list[dict[str, Any]]:
        """
        从“时间降序”消息中按预算挑选最新消息。

        规则：达到预算前持续添加；下一条会超预算时立即停止，不再追加更旧消息。
        """
        if token_budget <= 0 or not rows_descending:
            return []

        selected_desc: list[dict[str, Any]] = []
        used_tokens = 0

        for row in rows_descending:
            row_tokens = cls._row_token_count(row, model)
            if used_tokens + row_tokens > token_budget:
                break
            selected_desc.append(row)
            used_tokens += row_tokens

        selected_desc.reverse()
        return selected_desc

    async def _get_thresholds(self, user_id: str) -> WindowThresholds:
        """读取用户配置并计算窗口预算。"""
        config = await self.db.get_global_llm_config(user_id)
        total_limit = config.get("total_token_limit", DEFAULT_TOTAL_LIMIT)
        try:
            parsed_total_limit = int(total_limit)
        except Exception:  # noqa: BLE001
            parsed_total_limit = DEFAULT_TOTAL_LIMIT
        return WindowThresholds.from_total_limit(parsed_total_limit)

    def _build_message_from_tool_event_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """
        将 tool 区数据库行恢复为 OpenAI 协议消息。

        历史中 tool_call 以 assistant(role)+tool_calls 形式还原，
        tool_result 以 tool(role) 消息还原。
        """
        raw_content = str(row.get("content", ""))
        payload = self._parse_json_object(raw_content)
        if payload is None:
            return None

        event_name = str(payload.get("event", "")).strip()
        row_id = row.get("id")
        fallback_tool_call_id = f"tool_call_{row_id}" if row_id is not None else "tool_call_unknown"

        if event_name == "tool_call":
            tool_call_id = str(payload.get("tool_call_id", "")).strip() or fallback_tool_call_id
            tool_name = str(payload.get("tool_name", "")).strip() or f"unknown_tool_{tool_call_id}"
            arguments = self._to_json_string(payload.get("arguments", {}), default="{}")

            assistant_content: str | None = None
            raw_assistant_content = payload.get("assistant_content")
            if isinstance(raw_assistant_content, str) and raw_assistant_content.strip():
                assistant_content = raw_assistant_content

            return {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    }
                ],
            }

        if event_name == "tool_result":
            tool_call_id = str(payload.get("tool_call_id", "")).strip() or fallback_tool_call_id
            tool_name = str(payload.get("tool_name", "")).strip() or f"unknown_tool_{tool_call_id}"
            result_content = self._to_tool_content(payload.get("result", ""))
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": result_content,
            }

        return None

    def _sanitize_active_rows_for_tool_protocol(
        self,
        rows: list[dict[str, Any]],
        *,
        previous_role: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        清洗裁剪后的 active rows，避免出现工具协议顺序错误导致上游 400。

        规则：
        1) 非 tool 分区消息原样保留。
        2) tool_call 仅允许出现在 user/tool 之后，否则丢弃。
        3) tool_result 仅在对应 tool_call 已出现，且前一条为 assistant/tool 时保留。
        """
        sanitized: list[dict[str, Any]] = []
        known_tool_calls: set[str] = set()
        last_role = previous_role if previous_role in {"user", "assistant", "tool"} else None

        for row in rows:
            if str(row.get("zone", "")) != "tool":
                sanitized.append(row)
                normalized_role = self._normalize_prompt_role(row.get("role", "assistant"))
                # 非标准 tool 历史在构建 prompt 时会降级 assistant，这里同步维护角色游标。
                last_role = "assistant" if normalized_role == "tool" else normalized_role
                continue

            payload = self._parse_json_object(str(row.get("content", "")))
            if payload is None:
                continue

            event_name = str(payload.get("event", "")).strip()
            row_id = row.get("id")
            fallback_id = f"tool_call_{row_id}" if row_id is not None else "tool_call_unknown"
            tool_call_id = str(payload.get("tool_call_id", "")).strip() or fallback_id

            if event_name == "tool_call":
                if last_role not in {"user", "tool"}:
                    # 裁剪边界可能切掉了触发该 tool_call 的 user/tool，上游会直接 400，这里丢弃。
                    continue
                known_tool_calls.add(tool_call_id)
                sanitized.append(row)
                last_role = "assistant"
                continue

            if event_name == "tool_result":
                if tool_call_id in known_tool_calls and last_role in {"assistant", "tool"}:
                    sanitized.append(row)
                    last_role = "tool"
                continue

        return sanitized

    @staticmethod
    def _is_tool_persistable_event(event: dict[str, Any]) -> bool:
        """仅保留 tool_call/tool_result 到数据库。"""
        return str(event.get("event", "")) in {"tool_call", "tool_result"}

    async def _persist_tool_events(
        self,
        *,
        user_id: str,
        session_id: str,
        events: list[dict[str, Any]],
        model: str,
    ) -> None:
        """将工具事件按顺序落库到 tool 分区。"""
        for event in events:
            if not self._is_tool_persistable_event(event):
                continue
            role = "assistant" if event.get("event") == "tool_call" else "tool"
            content = json.dumps(event, ensure_ascii=False)
            await self.db.add_message(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                zone="tool",
                token_count=self._count_tokens(content, model),
            )

    async def _compose_resident_system_text(
        self,
        user_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> str:
        """
        生成常驻 system 文本：
        - 系统提示词 + 记忆文件：10%
        - 工作台摘要：1%
        """
        session = await self.db.get_session(user_id, session_id)
        try:
            system_prompt_markdown = await read_memory_file_impl(
                user_id=user_id,
                file_name=SYSTEM_PROMPT_FILE,
            )
        except FileNotFoundError:
            system_prompt_markdown = ""

        rules_text, tool_defs_text = self._split_system_prompt_sections(system_prompt_markdown)
        if not rules_text:
            rules_text = "(未配置规则，默认按用户意图回答并谨慎调用工具)"
        if not tool_defs_text:
            tool_defs_text = self._render_tool_definitions_from_schema()

        memory_sections: list[str] = []
        for file_name in list_memory_file_names(user_id):
            if file_name in {SYSTEM_PROMPT_FILE, ASSET_PLACEHOLDER_FILE}:
                continue
            try:
                content = await read_memory_file_impl(user_id=user_id, file_name=file_name)
            except FileNotFoundError:
                continue
            stripped = content.strip()
            if not stripped:
                continue
            memory_sections.append(f"### {file_name}\n{stripped}")

        memory_joined = "\n\n".join(memory_sections) if memory_sections else "(暂无普通记忆文件)"
        system_prompt_payload = (
            f"{self._system_preamble(thresholds)}\n\n"
            f"### 规则\n{rules_text.strip()}\n\n"
            f"### 工具定义\n{tool_defs_text.strip()}\n\n"
            f"### 记忆文件\n{memory_joined}"
        ).strip()

        summary_text = (session.get("workbench_summary") or "").strip() or "(当前暂无工作台摘要)"

        system_prompt_section = self._fit_section_to_budget(
            section_title=f"系统提示词与记忆文件（预算 {thresholds.system_prompt_limit} token）",
            content=system_prompt_payload,
            token_budget=thresholds.system_prompt_limit,
            model=model,
        )
        summary_section = self._fit_section_to_budget(
            section_title=f"工作台摘要（预算 {thresholds.summary_limit} token）",
            content=summary_text,
            token_budget=thresholds.summary_limit,
            model=model,
        )
        return f"{system_prompt_section}\n\n{summary_section}".strip()

    async def _build_chat_messages(
        self,
        user_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> list[dict[str, Any]]:
        """构建发给模型的完整 messages（含 resident_recent/dialogue/tool/buffer）。"""
        resident_text = await self._compose_resident_system_text(user_id, session_id, model, thresholds)

        resident_recent_all = await self.db.list_messages(
            user_id,
            session_id,
            zones=["resident_recent"],
            ascending=True,
        )
        resident_recent = self._take_latest_rows_by_token_budget(
            rows_ascending=resident_recent_all,
            token_budget=thresholds.recent_raw_limit,
            model=model,
        )

        active_all = await self.db.list_messages(
            user_id,
            session_id,
            zones=["dialogue", "tool", "buffer"],
            ascending=True,
        )
        active_messages = self._take_latest_rows_by_token_budget(
            rows_ascending=active_all,
            token_budget=thresholds.dialogue_limit,
            model=model,
        )
        previous_role: str | None = None
        for row in reversed(resident_recent):
            normalized_role = self._normalize_prompt_role(row.get("role", "assistant"))
            if normalized_role == "system":
                continue
            previous_role = "assistant" if normalized_role == "tool" else normalized_role
            break

        active_messages = self._sanitize_active_rows_for_tool_protocol(
            active_messages,
            previous_role=previous_role,
        )

        message_list: list[dict[str, Any]] = [{"role": "system", "content": resident_text}]
        for row in resident_recent + active_messages:
            if str(row.get("zone", "")) == "tool":
                tool_message = self._build_message_from_tool_event_row(row)
                if tool_message is not None:
                    message_list.append(tool_message)
                    continue

            role = self._normalize_prompt_role(row.get("role", "assistant"))
            if role == "tool":
                # 非标准 tool 历史格式降级为 assistant 文本，避免触发上游 400。
                role = "assistant"
            message_list.append({"role": role, "content": str(row.get("content", ""))})
        return message_list

    async def _resident_static_tokens(
        self,
        user_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> int:
        """统计常驻静态区 token（不含 resident_recent）。"""
        text = await self._compose_resident_system_text(user_id, session_id, model, thresholds)
        return self._count_tokens(text, model)

    async def get_status(
        self,
        user_id: str,
        session_id: str,
        model: str = "agent-advoo",
    ) -> MemoryStatusResponse:
        """读取会话当前 token 使用状态。"""
        session = await self.db.get_session(user_id, session_id)
        thresholds = await self._get_thresholds(user_id)
        zone_tokens = await self.db.sum_tokens_by_zone(user_id, session_id)

        resident_recent_all = await self.db.list_messages(
            user_id,
            session_id,
            zones=["resident_recent"],
            ascending=True,
        )
        resident_recent_limited = self._take_latest_rows_by_token_budget(
            rows_ascending=resident_recent_all,
            token_budget=thresholds.recent_raw_limit,
            model=model,
        )
        resident_recent_tokens = sum(self._row_token_count(row, model) for row in resident_recent_limited)

        # 常驻区由静态文本和近期保留对话共同构成。
        resident_static_tokens = await self._resident_static_tokens(user_id, session_id, model, thresholds)
        resident_tokens = resident_static_tokens + resident_recent_tokens

        dialogue_tokens = zone_tokens.get("dialogue", 0) + zone_tokens.get("tool", 0)
        buffer_tokens = zone_tokens.get("buffer", 0)
        total_tokens = resident_tokens + dialogue_tokens + buffer_tokens

        return MemoryStatusResponse(
            user_id=user_id,
            session_id=session_id,
            total_tokens=total_tokens,
            resident_tokens=resident_tokens,
            dialogue_tokens=dialogue_tokens,
            buffer_tokens=buffer_tokens,
            is_flushing=bool(session.get("is_flushing", False)),
            thresholds=thresholds.as_dict(),
        )

    async def process_chat(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
    ) -> ChatProcessResult:
        """处理一轮聊天请求，并在需要时标记异步刷盘。"""
        lock = await self._get_session_lock(user_id, session_id)
        live_tool_events: list[dict[str, Any]] = []

        async def _collect_tool_event(event: dict[str, Any]) -> None:
            live_tool_events.append(event)
            if on_event is None:
                return
            maybe_coro = on_event(event)
            if maybe_coro is not None:
                await maybe_coro

        async def _refresh_system_message() -> str:
            latest_thresholds = await self._get_thresholds(user_id)
            return await self._compose_resident_system_text(
                user_id=user_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=latest_thresholds,
            )

        async with lock:
            await self.db.ensure_session(user_id, session_id)
            session = await self.db.get_session(user_id, session_id)
            thresholds = await self._get_thresholds(user_id)

            # 刷盘中产生的新消息进入缓冲区，避免干扰归档输入。
            message_zone = "buffer" if session["is_flushing"] else "dialogue"
            await self.db.add_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_message,
                zone=message_zone,
                token_count=self._count_tokens(user_message, llm_config.model),
            )
            prompt_messages = await self._build_chat_messages(
                user_id=user_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=thresholds,
            )

            agent_result: AgentRunResult = await run_agent_with_tools(
                user_id=user_id,
                messages=prompt_messages,
                llm_config=llm_config,
                max_tool_rounds=max_tool_rounds,
                on_event=_collect_tool_event,
                refresh_system_message=_refresh_system_message,
            )

            session_after = await self.db.get_session(user_id, session_id)
            assistant_zone = "buffer" if session_after["is_flushing"] else "dialogue"

            # 工具事件先落库，再落助手最终回复，确保历史顺序可回放。
            await self._persist_tool_events(
                user_id=user_id,
                session_id=session_id,
                events=live_tool_events,
                model=llm_config.model,
            )

            assistant_text = agent_result.assistant_text or ""
            await self.db.add_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                zone=assistant_zone,
                token_count=self._count_tokens(assistant_text, llm_config.model),
            )

            status = await self.get_status(user_id, session_id, llm_config.model)
            flush_scheduled = False
            flush_trigger = int(status.thresholds.get("flush_trigger", thresholds.total_limit))
            if status.total_tokens >= flush_trigger and not session_after["is_flushing"]:
                # 严格在总 token 上限处触发刷盘，不再提前到 95%。
                await self.db.set_is_flushing(user_id, session_id, True)
                flush_scheduled = True
                status = status.model_copy(update={"is_flushing": True})

        return ChatProcessResult(
            assistant_text=agent_result.assistant_text,
            tool_events=live_tool_events,
            usage=agent_result.usage,
            status=status,
            flush_scheduled=flush_scheduled,
        )

    async def try_start_manual_flush(self, user_id: str, session_id: str) -> bool:
        """尝试手动启动刷盘；若已在刷盘中返回 False。"""
        lock = await self._get_session_lock(user_id, session_id)
        async with lock:
            await self.db.ensure_session(user_id, session_id)
            session = await self.db.get_session(user_id, session_id)
            if session["is_flushing"]:
                return False
            await self.db.set_is_flushing(user_id, session_id, True)
            return True

    async def flush_session_memory(
        self,
        user_id: str,
        session_id: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
    ) -> None:
        """执行刷盘：归档对话、重建 recent、更新工作台摘要并结束 flushing。"""
        lock = await self._get_session_lock(user_id, session_id)

        async with lock:
            await self.db.ensure_session(user_id, session_id)
            session = await self.db.get_session(user_id, session_id)
            if not session["is_flushing"]:
                await self.db.set_is_flushing(user_id, session_id, True)

            thresholds = await self._get_thresholds(user_id)

            dialogue_rows = await self.db.list_messages(
                user_id,
                session_id,
                zones=["dialogue", "tool"],
                ascending=True,
            )
            dialogue_text = "\n".join(
                [f"[{row['role']}] {row['content']}" for row in dialogue_rows if str(row["content"]).strip()]
            )
            base_system = await self._compose_resident_system_text(
                user_id=user_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=thresholds,
            )

        summary_text = "（无新增对话，保持原摘要）"

        async def _refresh_system_message() -> str:
            latest_thresholds = await self._get_thresholds(user_id)
            return await self._compose_resident_system_text(
                user_id=user_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=latest_thresholds,
            )

        try:
            if dialogue_text.strip():
                archive_messages = [
                    {"role": "system", "content": f"{base_system}\n\n{ARCHIVE_SYSTEM_PROMPT}"},
                    {"role": "user", "content": f"以下是待归档对话记录：\n\n{dialogue_text}"},
                ]
                archive_result = await run_agent_with_tools(
                    user_id=user_id,
                    messages=archive_messages,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                    refresh_system_message=_refresh_system_message,
                )
                summary_text = archive_result.assistant_text.strip() or summary_text

            async with lock:
                # 9% 原始最近对话预算：按 token 动态回收，超限立即停止追加更旧消息。
                latest_dialogue_desc = await self.db.list_messages(
                    user_id,
                    session_id,
                    zones=["dialogue", "buffer"],
                    roles=["user", "assistant"],
                    ascending=False,
                    limit=5000,
                )
                latest_dialogue = self._take_latest_rows_from_desc_by_budget(
                    rows_descending=latest_dialogue_desc,
                    token_budget=thresholds.recent_raw_limit,
                    model=llm_config.model,
                )

                await self.db.clear_messages(user_id, session_id)
                for row in latest_dialogue:
                    content = str(row.get("content", ""))
                    role = str(row.get("role", "assistant"))
                    await self.db.add_message(
                        user_id=user_id,
                        session_id=session_id,
                        role=role,
                        content=content,
                        zone="resident_recent",
                        token_count=self._count_tokens(content, llm_config.model),
                    )

                await self.db.update_workbench_summary(user_id, session_id, summary_text)
                await self.db.set_is_flushing(user_id, session_id, False)
        except Exception:  # noqa: BLE001
            async with lock:
                await self.db.set_is_flushing(user_id, session_id, False)
            raise
