"""记忆上下文用例：管理窗口、摘要与刷盘生命周期。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.ports.repositories import (
    EventCallback,
    LLMGatewayPort,
    MemoryFileRepositoryPort,
    MessageRepositoryPort,
    SessionRepositoryPort,
    TokenCounterPort,
    UserSettingsRepositoryPort,
)
from domain.models import ChatProcessResult, LLMConfig, MemoryStatus
from domain.prompt_composer import PromptComposer
from domain.tool_protocol import (
    build_message_from_tool_event_row,
    is_tool_persistable_event,
    normalize_prompt_role,
    sanitize_active_rows_for_tool_protocol,
)
from domain.window_policy import DEFAULT_TOTAL_LIMIT, WindowThresholds


ARCHIVE_SYSTEM_PROMPT = (
    "你是一个记忆整理专员。请分析给定对话记录，并在必要时调用 "
    "`write_memory_file` 工具，将新设定追加到最合适的记忆文件中。"
    "整理完成后，请输出纯文本“工作台摘要”，用于后续常驻区快速加载。"
)


class MemoryContextService:
    """管理会话级记忆分区与刷盘生命周期。"""

    def __init__(
        self,
        *,
        session_repo: SessionRepositoryPort,
        message_repo: MessageRepositoryPort,
        settings_repo: UserSettingsRepositoryPort,
        memory_repo: MemoryFileRepositoryPort,
        llm_gateway: LLMGatewayPort,
        token_counter: TokenCounterPort,
    ) -> None:
        """注入记忆上下文服务依赖，并初始化会话级并发控制。"""
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.settings_repo = settings_repo
        self.memory_repo = memory_repo
        self.llm_gateway = llm_gateway
        self.token_counter = token_counter

        self.prompt_composer = PromptComposer(
            count_tokens=self.token_counter.count_tokens,
            truncate_text_to_tokens=self.token_counter.truncate_text_to_tokens,
        )
        self._session_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _get_session_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """获取会话级互斥锁，避免同一会话并发写入导致状态错乱。"""
        lock_key = (user_id, session_id)
        async with self._locks_guard:
            if lock_key not in self._session_locks:
                self._session_locks[lock_key] = asyncio.Lock()
            return self._session_locks[lock_key]

    async def _get_thresholds(self, user_id: str) -> WindowThresholds:
        """读取用户 token 配置并计算窗口阈值。"""
        settings = await self.settings_repo.get_global_settings(user_id)
        total_limit = settings.total_token_limit
        try:
            parsed_total_limit = int(total_limit)
        except Exception:  # noqa: BLE001
            parsed_total_limit = DEFAULT_TOTAL_LIMIT
        return WindowThresholds.from_total_limit(parsed_total_limit)

    async def _persist_tool_events(
        self,
        *,
        user_id: str,
        session_id: str,
        events: list[dict[str, Any]],
        model: str,
    ) -> None:
        """将可持久化的工具事件落库到 ``tool`` 分区。"""
        for event in events:
            if not is_tool_persistable_event(event):
                continue
            # tool_call 用 assistant 角色承载，tool_result 用 tool 角色承载，
            # 以便后续重建符合协议顺序的上下文。
            role = "assistant" if event.get("event") == "tool_call" else "tool"
            content = json.dumps(event, ensure_ascii=False)
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                zone="tool",
                token_count=self.token_counter.count_tokens(content, model),
            )

    async def _compose_resident_system_text(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> str:
        """按当前会话状态拼装常驻 system 提示词。"""
        session = await self.session_repo.get_session(user_id, session_id)
        return await self.prompt_composer.compose_resident_system_text(
            user_id=user_id,
            employee_id=employee_id,
            session=session,
            model=model,
            thresholds=thresholds,
            list_memory_files=self.memory_repo.list_memory_file_names,
            read_memory_file=self.memory_repo.read_memory_file,
        )

    async def _build_chat_messages(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> list[dict[str, Any]]:
        """构建发给 LLM 的消息列表（system + recent + active）。"""
        resident_text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            model,
            thresholds,
        )

        # resident_recent 只保留最近预算内内容，控制提示词膨胀。
        resident_recent_all = await self.message_repo.list_messages(
            user_id,
            session_id,
            zones=["resident_recent"],
            ascending=True,
        )
        resident_recent = self.prompt_composer.take_latest_rows_by_token_budget(
            rows_ascending=resident_recent_all,
            token_budget=thresholds.recent_raw_limit,
            model=model,
        )

        active_all = await self.message_repo.list_messages(
            user_id,
            session_id,
            zones=["dialogue", "tool", "buffer"],
            ascending=True,
        )
        active_messages = self.prompt_composer.take_latest_rows_by_token_budget(
            rows_ascending=active_all,
            token_budget=thresholds.dialogue_limit,
            model=model,
        )

        # 修复裁剪后可能出现的工具协议断裂（如孤立 tool result）。
        previous_role = self.prompt_composer.previous_role_from_resident_recent(resident_recent)
        active_messages = sanitize_active_rows_for_tool_protocol(
            active_messages,
            previous_role=previous_role,
        )

        message_list: list[dict[str, Any]] = [{"role": "system", "content": resident_text}]
        for row in resident_recent + active_messages:
            if str(row.get("zone", "")) == "tool":
                # tool 分区消息需要还原为 OpenAI tool_call/tool_result 结构。
                tool_message = build_message_from_tool_event_row(row)
                if tool_message is not None:
                    message_list.append(tool_message)
                    continue

            role = normalize_prompt_role(row.get("role", "assistant"))
            if role == "tool":
                role = "assistant"
            message_list.append({"role": role, "content": str(row.get("content", ""))})
        return message_list

    async def _resident_static_tokens(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str,
        thresholds: WindowThresholds,
    ) -> int:
        """估算常驻 system 静态部分的 token 消耗。"""
        text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            model,
            thresholds,
        )
        return self.token_counter.count_tokens(text, model)

    async def get_status(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str = "agent-advoo",
    ) -> MemoryStatus:
        """聚合并返回会话当前记忆状态。"""
        session = await self.session_repo.get_session(user_id, session_id)
        thresholds = await self._get_thresholds(user_id)
        zone_tokens = await self.message_repo.sum_tokens_by_zone(user_id, session_id)

        resident_recent_all = await self.message_repo.list_messages(
            user_id,
            session_id,
            zones=["resident_recent"],
            ascending=True,
        )
        resident_recent_limited = self.prompt_composer.take_latest_rows_by_token_budget(
            rows_ascending=resident_recent_all,
            token_budget=thresholds.recent_raw_limit,
            model=model,
        )
        resident_recent_tokens = sum(
            self.prompt_composer.row_token_count(row, model) for row in resident_recent_limited
        )

        # 总 token = 常驻静态 + 常驻近期 + 对话区 + 缓冲区。
        resident_static_tokens = await self._resident_static_tokens(
            user_id,
            employee_id,
            session_id,
            model,
            thresholds,
        )
        resident_tokens = resident_static_tokens + resident_recent_tokens

        dialogue_tokens = zone_tokens.get("dialogue", 0) + zone_tokens.get("tool", 0)
        buffer_tokens = zone_tokens.get("buffer", 0)
        total_tokens = resident_tokens + dialogue_tokens + buffer_tokens

        return MemoryStatus(
            user_id=user_id,
            employee_id=employee_id,
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
        employee_id: str,
        session_id: str,
        user_message: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
    ) -> ChatProcessResult:
        """处理一次聊天请求，并返回回复、事件及记忆状态。"""
        lock = await self._get_session_lock(user_id, session_id)
        live_tool_events: list[dict[str, Any]] = []

        async def collect_tool_event(event: dict[str, Any]) -> None:
            """收集工具事件并按需透传给外部 SSE 回调。"""
            live_tool_events.append(event)
            if on_event is None:
                return
            maybe_coro = on_event(event)
            if maybe_coro is not None:
                await maybe_coro

        async def refresh_system_message() -> str:
            """供工具链在写入记忆后刷新 system 提示词。"""
            latest_thresholds = await self._get_thresholds(user_id)
            return await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=latest_thresholds,
            )

        async with lock:
            # 1) 写入用户消息，刷盘期间写入 buffer 分区，避免污染当前对话窗口。
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            thresholds = await self._get_thresholds(user_id)

            message_zone = "buffer" if session["is_flushing"] else "dialogue"
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                content=user_message,
                zone=message_zone,
                token_count=self.token_counter.count_tokens(user_message, llm_config.model),
            )
            prompt_messages = await self._build_chat_messages(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=thresholds,
            )

            # 2) 调用 LLM（含工具循环）。
            agent_result = await self.llm_gateway.run_with_tools(
                user_id=user_id,
                employee_id=employee_id,
                messages=prompt_messages,
                llm_config=llm_config,
                max_tool_rounds=max_tool_rounds,
                on_event=collect_tool_event,
                refresh_system_message=refresh_system_message,
            )

            session_after = await self.session_repo.get_session(user_id, session_id)
            assistant_zone = "buffer" if session_after["is_flushing"] else "dialogue"

            # 3) 先落库工具事件，再落库 assistant 最终文本，保证重放顺序稳定。
            await self._persist_tool_events(
                user_id=user_id,
                session_id=session_id,
                events=live_tool_events,
                model=llm_config.model,
            )

            assistant_text = agent_result.assistant_text or ""
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=assistant_text,
                zone=assistant_zone,
                token_count=self.token_counter.count_tokens(assistant_text, llm_config.model),
            )

            status = await self.get_status(user_id, employee_id, session_id, llm_config.model)
            flush_scheduled = False
            flush_trigger = int(status.thresholds.get("flush_trigger", thresholds.total_limit))
            if status.total_tokens >= flush_trigger and not session_after["is_flushing"]:
                # 触发阈值后只打标记，不在这里执行刷盘；实际刷盘由外层后台任务接管。
                await self.session_repo.set_is_flushing(user_id, session_id, True)
                flush_scheduled = True
                status = MemoryStatus(
                    user_id=status.user_id,
                    employee_id=status.employee_id,
                    session_id=status.session_id,
                    total_tokens=status.total_tokens,
                    resident_tokens=status.resident_tokens,
                    dialogue_tokens=status.dialogue_tokens,
                    buffer_tokens=status.buffer_tokens,
                    is_flushing=True,
                    thresholds=status.thresholds,
                )

        return ChatProcessResult(
            assistant_text=agent_result.assistant_text,
            tool_events=live_tool_events,
            usage=agent_result.usage,
            status=status,
            flush_scheduled=flush_scheduled,
        )

    async def try_start_manual_flush(self, user_id: str, session_id: str) -> bool:
        """尝试进入手动刷盘状态，返回是否抢占成功。"""
        lock = await self._get_session_lock(user_id, session_id)
        async with lock:
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            if session["is_flushing"]:
                return False
            await self.session_repo.set_is_flushing(user_id, session_id, True)
            return True

    async def flush_session_memory(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
        max_tool_rounds: int,
    ) -> None:
        """执行会话刷盘：归档摘要、重建常驻近期窗口并清理分区。"""
        lock = await self._get_session_lock(user_id, session_id)

        async with lock:
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            if not session["is_flushing"]:
                await self.session_repo.set_is_flushing(user_id, session_id, True)

            thresholds = await self._get_thresholds(user_id)

            dialogue_rows = await self.message_repo.list_messages(
                user_id,
                session_id,
                zones=["dialogue", "tool"],
                ascending=True,
            )
            # 将对话区和工具区拼成归档文本，作为“记忆整理专员”的输入。
            dialogue_text = "\n".join(
                [f"[{row['role']}] {row['content']}" for row in dialogue_rows if str(row["content"]).strip()]
            )
            base_system = await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=thresholds,
            )

        summary_text = "（无新增对话，保持原摘要）"

        async def refresh_system_message() -> str:
            """归档阶段写入记忆文件后，实时刷新 system 文本。"""
            latest_thresholds = await self._get_thresholds(user_id)
            return await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                model=llm_config.model,
                thresholds=latest_thresholds,
            )

        try:
            if dialogue_text.strip():
                # 对话非空时调用 LLM 执行归档总结，并允许工具写入记忆文件。
                archive_messages = [
                    {"role": "system", "content": f"{base_system}\n\n{ARCHIVE_SYSTEM_PROMPT}"},
                    {"role": "user", "content": f"以下是待归档对话记录：\n\n{dialogue_text}"},
                ]
                archive_result = await self.llm_gateway.run_with_tools(
                    user_id=user_id,
                    employee_id=employee_id,
                    messages=archive_messages,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                    refresh_system_message=refresh_system_message,
                )
                summary_text = archive_result.assistant_text.strip() or summary_text

            async with lock:
                # 按最近窗口预算回收可保留消息，随后清空并重建 resident_recent 分区。
                latest_dialogue_desc = await self.message_repo.list_messages(
                    user_id,
                    session_id,
                    zones=["dialogue", "buffer"],
                    roles=["user", "assistant"],
                    ascending=False,
                    limit=5000,
                )
                latest_dialogue = self.prompt_composer.take_latest_rows_from_desc_by_budget(
                    rows_descending=latest_dialogue_desc,
                    token_budget=thresholds.recent_raw_limit,
                    model=llm_config.model,
                )

                await self.message_repo.clear_messages(user_id, session_id)
                for row in latest_dialogue:
                    content = str(row.get("content", ""))
                    role = str(row.get("role", "assistant"))
                    await self.message_repo.add_message(
                        user_id=user_id,
                        session_id=session_id,
                        role=role,
                        content=content,
                        zone="resident_recent",
                        token_count=self.token_counter.count_tokens(content, llm_config.model),
                    )

                await self.session_repo.update_workbench_summary(user_id, session_id, summary_text)
                await self.session_repo.set_is_flushing(user_id, session_id, False)
        except Exception:  # noqa: BLE001
            # 任意异常都要回收 flushing 标记，避免会话永久卡住。
            async with lock:
                await self.session_repo.set_is_flushing(user_id, session_id, False)
            raise
