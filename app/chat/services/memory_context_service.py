"""聊天记忆上下文服务：管理窗口、摘要与刷盘生命周期。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.chat.services.session_lock_registry import SessionLockRegistry
from app.chat.services.window_config_service import DEFAULT_TOKENIZER_MODEL, WindowConfigService
from app.ports.repositories import (
    EventCallback,
    LLMGatewayPort,
    MemoryFileRepositoryPort,
    MessageRepositoryPort,
    SessionRepositoryPort,
    ToolSchemaProviderPort,
    TokenCounterPort,
    UserSettingsRepositoryPort,
)
from common.errors import ValidationError
from domain.models import ChatProcessResult, LLMConfig, MemoryStatus
from domain.prompt_composer import PromptComposer
from domain.prompt_templates import compose_flush_archive_system_prompt
from domain.tool_protocol import (
    build_message_from_tool_event_row,
    is_tool_persistable_event,
    normalize_message_kind,
    normalize_prompt_role,
    sanitize_active_rows_for_tool_protocol,
)
from domain.window_policy import WindowThresholds


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
        tool_schema_provider: ToolSchemaProviderPort | None = None,
    ) -> None:
        """注入记忆上下文服务依赖，并初始化会话级并发控制。"""
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.settings_repo = settings_repo
        self.memory_repo = memory_repo
        self.llm_gateway = llm_gateway
        self.token_counter = token_counter
        self.tool_schema_provider = tool_schema_provider
        self.window_config_service = WindowConfigService(settings_repo)
        self.session_lock_registry = SessionLockRegistry()

        self.prompt_composer = PromptComposer(
            count_tokens=self.token_counter.count_tokens,
            truncate_text_to_tokens=self.token_counter.truncate_text_to_tokens,
        )

    @staticmethod
    def _ensure_buffer_capacity(*, existing_tokens: int, incoming_tokens: int, buffer_limit: int) -> None:
        """刷盘期间校验缓冲区容量，超限时拒绝新消息。"""
        if existing_tokens + incoming_tokens <= buffer_limit:
            return
        raise ValidationError(
            "当前会话正在刷盘，缓冲区已满，请稍后重试。"
            f"（buffer={existing_tokens} + incoming={incoming_tokens} > limit={buffer_limit}）"
        )

    def _list_tool_schemas(self) -> list[dict[str, Any]]:
        """返回当前可用于提示词渲染的工具 Schema 列表。"""
        provider = self.tool_schema_provider
        if provider is None:
            return []
        try:
            schemas = provider.list_tool_schemas()
        except Exception:  # noqa: BLE001
            return []
        return [item for item in schemas if isinstance(item, dict)]

    async def _get_session_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """获取会话级互斥锁，避免同一会话并发写入导致状态错乱。"""
        return await self.session_lock_registry.get_lock(user_id, session_id)

    async def _get_window_config(
        self,
        user_id: str,
        *,
        fallback_model: str = DEFAULT_TOKENIZER_MODEL,
    ) -> tuple[WindowThresholds, str]:
        """读取 token 窗口阈值与 tokenizer 选型。"""
        return await self.window_config_service.get_window_config(
            user_id,
            fallback_model=fallback_model,
        )

    async def _persist_tool_events(
        self,
        *,
        user_id: str,
        session_id: str,
        events: list[dict[str, Any]],
        tokenizer_model: str,
        zone: str,
        buffer_limit: int,
    ) -> None:
        """将可持久化的工具事件落库到目标生命周期分区。"""
        buffer_tokens = 0
        if zone == "buffer":
            zone_tokens = await self.message_repo.sum_tokens_by_zone(user_id, session_id)
            buffer_tokens = zone_tokens.get("buffer", 0)

        for event in events:
            if not is_tool_persistable_event(event):
                continue
            event_name = str(event.get("event", "")).strip()
            if event_name == "tool_call":
                role = "assistant"
                message_kind = "tool_call"
            elif event_name == "tool_result":
                role = "tool"
                message_kind = "tool_result"
            else:
                continue

            content = json.dumps(event, ensure_ascii=False)
            token_count = self.token_counter.count_tokens(content, tokenizer_model)
            if zone == "buffer":
                self._ensure_buffer_capacity(
                    existing_tokens=buffer_tokens,
                    incoming_tokens=token_count,
                    buffer_limit=buffer_limit,
                )
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role=role,
                message_kind=message_kind,
                content=content,
                zone=zone,
                token_count=token_count,
            )
            if zone == "buffer":
                buffer_tokens += token_count

    async def _compose_resident_system_text(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        tokenizer_model: str,
        thresholds: WindowThresholds,
    ) -> str:
        """按当前会话状态拼装常驻 system 提示词。"""
        session = await self.session_repo.get_session(user_id, session_id)
        return await self.prompt_composer.compose_resident_system_text(
            user_id=user_id,
            employee_id=employee_id,
            session=session,
            model=tokenizer_model,
            thresholds=thresholds,
            list_memory_files=self.memory_repo.list_memory_file_names,
            read_memory_file=self.memory_repo.read_memory_file,
            tool_schemas=self._list_tool_schemas(),
        )

    async def _build_chat_messages(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        tokenizer_model: str,
        thresholds: WindowThresholds,
    ) -> list[dict[str, Any]]:
        """构建发给 LLM 的消息列表（system + recent + active）。"""
        resident_text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            tokenizer_model,
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
            model=tokenizer_model,
        )

        active_all = await self.message_repo.list_messages(
            user_id,
            session_id,
            zones=["dialogue", "buffer"],
            ascending=True,
        )
        active_messages = self.prompt_composer.take_latest_rows_by_token_budget(
            rows_ascending=active_all,
            token_budget=thresholds.dialogue_limit,
            model=tokenizer_model,
        )

        # 修复裁剪后可能出现的工具协议断裂（如孤立 tool result）。
        previous_role = self.prompt_composer.previous_role_from_resident_recent(resident_recent)
        active_messages = sanitize_active_rows_for_tool_protocol(
            active_messages,
            previous_role=previous_role,
        )

        message_list: list[dict[str, Any]] = [{"role": "system", "content": resident_text}]
        for row in resident_recent + active_messages:
            message_kind = normalize_message_kind(row)
            if message_kind in {"tool_call", "tool_result"}:
                # 工具类型消息需要还原为 OpenAI tool_call/tool_result 结构。
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
        tokenizer_model: str,
        thresholds: WindowThresholds,
    ) -> int:
        """估算常驻 system 静态部分的 token 消耗。"""
        text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            tokenizer_model,
            thresholds,
        )
        return self.token_counter.count_tokens(text, tokenizer_model)

    async def get_status(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str = "agent-advoo",
    ) -> MemoryStatus:
        """聚合并返回会话当前记忆状态。"""
        session = await self.session_repo.get_session(user_id, session_id)
        thresholds, tokenizer_model = await self._get_window_config(
            user_id,
            fallback_model=model,
        )
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
            model=tokenizer_model,
        )
        resident_recent_tokens = sum(
            self.prompt_composer.row_token_count(row, tokenizer_model) for row in resident_recent_limited
        )

        # 总 token = 常驻静态 + 常驻近期 + 对话区 + 缓冲区。
        resident_static_tokens = await self._resident_static_tokens(
            user_id,
            employee_id,
            session_id,
            tokenizer_model,
            thresholds,
        )
        resident_tokens = resident_static_tokens + resident_recent_tokens

        dialogue_tokens = zone_tokens.get("dialogue", 0)
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
            latest_thresholds, latest_tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )
            return await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                tokenizer_model=latest_tokenizer_model,
                thresholds=latest_thresholds,
            )

        async with lock:
            # 1) 写入用户消息，刷盘期间写入 buffer 分区，避免污染当前对话窗口。
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            thresholds, tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )

            message_zone = "buffer" if session["is_flushing"] else "dialogue"
            user_token_count = self.token_counter.count_tokens(user_message, tokenizer_model)
            if message_zone == "buffer":
                zone_tokens = await self.message_repo.sum_tokens_by_zone(user_id, session_id)
                self._ensure_buffer_capacity(
                    existing_tokens=zone_tokens.get("buffer", 0),
                    incoming_tokens=user_token_count,
                    buffer_limit=thresholds.buffer_limit,
                )
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role="user",
                message_kind="chat",
                content=user_message,
                zone=message_zone,
                token_count=user_token_count,
            )
            prompt_messages = await self._build_chat_messages(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                tokenizer_model=tokenizer_model,
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
                tokenizer_model=tokenizer_model,
                zone=assistant_zone,
                buffer_limit=thresholds.buffer_limit,
            )

            assistant_text = agent_result.assistant_text or ""
            assistant_token_count = self.token_counter.count_tokens(assistant_text, tokenizer_model)
            if assistant_zone == "buffer":
                zone_tokens = await self.message_repo.sum_tokens_by_zone(user_id, session_id)
                self._ensure_buffer_capacity(
                    existing_tokens=zone_tokens.get("buffer", 0),
                    incoming_tokens=assistant_token_count,
                    buffer_limit=thresholds.buffer_limit,
                )
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                message_kind="chat",
                content=assistant_text,
                zone=assistant_zone,
                token_count=assistant_token_count,
            )

            status = await self.get_status(user_id, employee_id, session_id, tokenizer_model)
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

            thresholds, tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )

            dialogue_rows = await self.message_repo.list_messages(
                user_id,
                session_id,
                zones=["dialogue"],
                ascending=True,
            )
            # 将旧 dialogue 区（含 chat/tool_* 类型）拼成归档文本，作为“记忆整理专员”的输入。
            dialogue_text = "\n".join(
                [f"[{row['role']}] {row['content']}" for row in dialogue_rows if str(row["content"]).strip()]
            )
            base_system = await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                tokenizer_model=tokenizer_model,
                thresholds=thresholds,
            )

        summary_text = "（无新增对话，保持原摘要）"

        async def refresh_system_message() -> str:
            """归档阶段写入记忆文件后，实时刷新 system 文本。"""
            latest_thresholds, latest_tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )
            return await self._compose_resident_system_text(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                tokenizer_model=latest_tokenizer_model,
                thresholds=latest_thresholds,
            )

        try:
            if dialogue_text.strip():
                # 对话非空时调用 LLM 执行归档总结，并允许工具写入记忆文件。
                archive_messages = [
                    {
                        "role": "system",
                        "content": compose_flush_archive_system_prompt(resident_base_system=base_system),
                    },
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
                # 按最近窗口预算从旧 dialogue 回收可保留消息。
                latest_dialogue_desc = await self.message_repo.list_messages(
                    user_id,
                    session_id,
                    zones=["dialogue"],
                    roles=["user", "assistant"],
                    message_kinds=["chat"],
                    ascending=False,
                    limit=5000,
                )
                # 收集刷盘期间新增的 buffer 消息，刷盘完成后迁回 dialogue。
                buffer_rows = await self.message_repo.list_messages(
                    user_id,
                    session_id,
                    zones=["buffer"],
                    ascending=True,
                )
                latest_dialogue = self.prompt_composer.take_latest_rows_from_desc_by_budget(
                    rows_descending=latest_dialogue_desc,
                    token_budget=thresholds.recent_raw_limit,
                    model=tokenizer_model,
                )

                await self.message_repo.clear_messages(user_id, session_id)
                for row in latest_dialogue:
                    content = str(row.get("content", ""))
                    role = str(row.get("role", "assistant"))
                    await self.message_repo.add_message(
                        user_id=user_id,
                        session_id=session_id,
                        role=role,
                        message_kind="chat",
                        content=content,
                        zone="resident_recent",
                        token_count=self.token_counter.count_tokens(content, tokenizer_model),
                    )
                for row in buffer_rows:
                    content = str(row.get("content", ""))
                    role = str(row.get("role", "assistant"))
                    message_kind = str(row.get("message_kind", "chat")).strip() or "chat"
                    await self.message_repo.add_message(
                        user_id=user_id,
                        session_id=session_id,
                        role=role,
                        message_kind=message_kind,
                        content=content,
                        zone="dialogue",
                        token_count=self.prompt_composer.row_token_count(row, tokenizer_model),
                    )

                await self.session_repo.update_workbench_summary(user_id, session_id, summary_text)
                await self.session_repo.set_is_flushing(user_id, session_id, False)
        except Exception:  # noqa: BLE001
            # 任意异常都要回收 flushing 标记，避免会话永久卡住。
            async with lock:
                await self.session_repo.set_is_flushing(user_id, session_id, False)
            raise

