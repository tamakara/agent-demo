"""智能体核心应用服务。

该服务统一承载三条核心业务链路：
1. 聊天处理（消息写入、上下文构建、LLM 调用、事件落库）。
2. 记忆状态查询（各分区 token 汇总、压缩状态读取）。
3. 压缩流程（手动/自动触发、摘要归档、分区回收与迁移）。

设计要点：
- 所有外部能力都通过接口注入（仓储、LLM、token 计数、模板仓储等）。
- 服务本身不依赖具体框架或 SDK。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.errors import ValidationError
from app.interfaces import (
    IAgentEngine,
    EventCallback,
    IMemoryRepository,
    IMessageRepository,
    IPromptTemplateRepository,
    ISessionRepository,
    ISettingsRepository,
    ITokenCounter,
    IToolSchemaProvider,
)
from app.memory_specs import COMPRESSED_MEMORY_FILE, memory_file_token_limit
from app.prompt_composer import PromptComposer
from app.services.session_lock_registry import SessionLockRegistry
from app.services.window_config_service import DEFAULT_TOKENIZER_MODEL, WindowConfigService
from app.window_policy import WindowThresholds
from domain.models import ChatResult, CompressionResult, LLMConfig, MemoryStatus


class AgentService:
    """Agent 应用服务：对外提供聊天与记忆能力的统一入口。"""

    def __init__(
        self,
        *,
        session_repo: ISessionRepository,
        message_repo: IMessageRepository,
        settings_repo: ISettingsRepository,
        memory_repo: IMemoryRepository,
        agent_engine: IAgentEngine,
        token_counter: ITokenCounter,
        prompt_templates: IPromptTemplateRepository,
        tool_schema_provider: IToolSchemaProvider | None = None,
    ) -> None:
        # 基础仓储与外部能力依赖。
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.settings_repo = settings_repo
        self.memory_repo = memory_repo
        self.agent_engine = agent_engine
        self.token_counter = token_counter
        self.tool_schema_provider = tool_schema_provider

        # 业务辅助组件：窗口配置、会话锁、提示词组装。
        self.window_config_service = WindowConfigService(settings_repo)
        self.session_lock_registry = SessionLockRegistry()
        self.prompt_composer = PromptComposer(
            count_tokens=self.token_counter.count_tokens,
            truncate_text_to_tokens=self.token_counter.truncate_text_to_tokens,
            template_repository=prompt_templates,
        )
        self.prompt_templates = prompt_templates

    @staticmethod
    def _ensure_buffer_capacity(*, existing_tokens: int, incoming_tokens: int, buffer_limit: int) -> None:
        """压缩期缓冲区容量校验。"""
        if existing_tokens + incoming_tokens <= buffer_limit:
            return
        raise ValidationError(
            "当前会话正在压缩，缓冲区已满，请稍后重试。"
            f"（buffer={existing_tokens} + incoming={incoming_tokens} > limit={buffer_limit}）"
        )

    @staticmethod
    def _normalize_prompt_role(raw_role: Any) -> str:
        role = str(raw_role).strip().lower()
        if role in {"system", "user", "assistant"}:
            return role
        return "assistant"

    def _list_tool_schemas(self) -> list[dict[str, Any]]:
        """读取工具 schema 列表，失败时降级为空列表。"""
        provider = self.tool_schema_provider
        if provider is None:
            return []
        try:
            schemas = provider.list_tool_schemas()
        except Exception:  # noqa: BLE001
            return []
        return [item for item in schemas if isinstance(item, dict)]

    @staticmethod
    def _resolve_max_tool_rounds(llm_config: LLMConfig) -> int:
        """解析本次执行的工具轮次上限，保证最小为 1。"""
        return max(1, int(getattr(llm_config, "max_tool_rounds", 0) or 0))

    async def _get_session_lock(self, user_id: str, session_id: str) -> asyncio.Lock:
        """获取会话粒度互斥锁。"""
        return await self.session_lock_registry.get_lock(user_id, session_id)

    async def _get_window_config(
        self,
        user_id: str,
        *,
        fallback_model: str = DEFAULT_TOKENIZER_MODEL,
    ) -> tuple[WindowThresholds, str]:
        """读取窗口阈值配置并确定 tokenizer 模型。"""
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
    ) -> None:
        """持久化 Graph 执行事件到 debug 分区。"""
        persistable_events = {
            "graph_reasoning_start",
            "graph_reasoning_end",
            "graph_tool_start",
            "graph_tool_end",
            "graph_error",
        }

        for event in events:
            event_name = str(event.get("event", "")).strip()
            if event_name not in persistable_events:
                continue

            # Graph 执行事件属于观测信息，不进入模型上下文。
            content = json.dumps(event, ensure_ascii=False)
            await self.message_repo.add_message(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                message_kind="meta",
                content=content,
                zone="debug",
                token_count=0,
            )

    async def _compose_resident_system_text(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        tokenizer_model: str,
        thresholds: WindowThresholds,
    ) -> str:
        """构建常驻 system 文本（记忆文件 + 摘要 + 工具说明）。"""
        session = await self.session_repo.get_session(user_id, session_id)
        return await self.prompt_composer.compose_resident_system_text(
            user_id=user_id,
            employee_id=employee_id,
            session=session,
            model=tokenizer_model,
            thresholds=thresholds,
            read_memory_file=self.memory_repo.read_memory_file,
            tool_schemas=self._list_tool_schemas(),
        )

    @classmethod
    def _compression_memory_token_limit(cls, thresholds: WindowThresholds) -> int:
        """计算压缩流程可写入 `memory.md` 的 token 上限。"""
        limit = memory_file_token_limit(COMPRESSED_MEMORY_FILE, thresholds.total_limit)
        return max(1, int(limit or 1))

    async def _build_chat_messages(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        tokenizer_model: str,
        thresholds: WindowThresholds,
    ) -> list[dict[str, Any]]:
        """构建发给 LLM 的消息列表。"""
        resident_text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            tokenizer_model,
            thresholds,
        )

        # `resident_recent` 是压缩后保留的近期窗口。
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

        # active = 当前对话窗口（dialogue + buffer）。
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

        message_list: list[dict[str, Any]] = [{"role": "system", "content": resident_text}]
        for row in resident_recent + active_messages:
            role = self._normalize_prompt_role(row.get("role", "assistant"))
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
        """估算 system 常驻静态区 token 消耗。"""
        text = await self._compose_resident_system_text(
            user_id,
            employee_id,
            session_id,
            tokenizer_model,
            thresholds,
        )
        return self.token_counter.count_tokens(text, tokenizer_model)

    async def get_memory_status(
        self,
        user_id: str,
        employee_id: str,
        session_id: str,
        model: str = "agent-advoo",
    ) -> MemoryStatus:
        """聚合并返回会话记忆状态。"""
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

        # 总量 = resident(静态+近期) + dialogue + buffer。
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
            is_compressing=bool(session.get("is_compressing", False)),
            thresholds=thresholds.as_dict(),
        )

    async def stream_chat(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        user_message: str,
        llm_config: LLMConfig,
        on_event: EventCallback | None = None,
    ) -> ChatResult:
        """执行一次完整聊天流程。"""
        lock = await self._get_session_lock(user_id, session_id)
        live_tool_events: list[dict[str, Any]] = []
        max_tool_rounds = self._resolve_max_tool_rounds(llm_config)

        async def collect_tool_event(event: dict[str, Any]) -> None:
            """收集工具事件，并按需转发到上层 SSE 回调。"""
            live_tool_events.append(event)
            if on_event is None:
                return
            maybe_coro = on_event(event)
            if maybe_coro is not None:
                await maybe_coro

        async def refresh_system_message() -> str:
            """工具写入记忆后，供 LLM 工具循环刷新 system 提示词。"""
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
            # 1) 先写入用户消息：压缩期写入 buffer，非压缩期写入 dialogue。
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            thresholds, tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )

            message_zone = "buffer" if session["is_compressing"] else "dialogue"
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

            # 2) 调用 LLM（内部可包含多轮工具调用）。
            agent_result = await self.agent_engine.process(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                messages=prompt_messages,
                llm_config=llm_config,
                max_tool_rounds=max_tool_rounds,
                on_event=collect_tool_event,
                refresh_system_message=refresh_system_message,
                allow_hidden_memory_files=False,
            )

            session_after = await self.session_repo.get_session(user_id, session_id)
            assistant_zone = "buffer" if session_after["is_compressing"] else "dialogue"
            # 二次读取 session，避免“LLM 执行期间压缩态切换”导致落库分区不一致。

            # 3) 先落工具事件，再落 assistant 文本，保证回放顺序稳定。
            persisted_tool_events = agent_result.tool_events or live_tool_events
            await self._persist_tool_events(
                user_id=user_id,
                session_id=session_id,
                events=persisted_tool_events,
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

            # 4) 计算状态并按阈值决定是否触发后台压缩。
            status = await self.get_memory_status(user_id, employee_id, session_id, tokenizer_model)
            compression_scheduled = False
            compression_trigger = int(status.thresholds.get("compression_trigger", thresholds.total_limit))
            if status.total_tokens >= compression_trigger and not session_after["is_compressing"]:
                await self.session_repo.set_is_compressing(user_id, session_id, True)
                compression_scheduled = True
                status = MemoryStatus(
                    user_id=status.user_id,
                    employee_id=status.employee_id,
                    session_id=status.session_id,
                    total_tokens=status.total_tokens,
                    resident_tokens=status.resident_tokens,
                    dialogue_tokens=status.dialogue_tokens,
                    buffer_tokens=status.buffer_tokens,
                    is_compressing=True,
                    thresholds=status.thresholds,
                )

        return ChatResult(
            assistant_text=agent_result.assistant_text,
            tool_events=persisted_tool_events,
            usage=agent_result.usage,
            status=status,
            compression_scheduled=compression_scheduled,
        )

    async def try_start_manual_compression(self, user_id: str, session_id: str) -> bool:
        """尝试抢占手动压缩执行权。"""
        lock = await self._get_session_lock(user_id, session_id)
        async with lock:
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            if session["is_compressing"]:
                return False
            await self.session_repo.set_is_compressing(user_id, session_id, True)
            return True

    async def compress_session_memory(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
    ) -> None:
        """执行压缩流程并重建窗口分区。"""
        lock = await self._get_session_lock(user_id, session_id)
        max_tool_rounds = self._resolve_max_tool_rounds(llm_config)

        async with lock:
            await self.session_repo.ensure_session(user_id, session_id)
            session = await self.session_repo.get_session(user_id, session_id)
            if not session["is_compressing"]:
                await self.session_repo.set_is_compressing(user_id, session_id, True)

            thresholds, tokenizer_model = await self._get_window_config(
                user_id,
                fallback_model=llm_config.model,
            )

            # 读取旧 dialogue 作为归档输入。
            dialogue_rows = await self.message_repo.list_messages(
                user_id,
                session_id,
                zones=["dialogue"],
                ascending=True,
            )
            dialogue_text = "\n".join(
                [f"[{row['role']}] {row['content']}" for row in dialogue_rows if str(row["content"]).strip()]
            )

        summary_text = "（无新增对话，保持原摘要）"

        try:
            if dialogue_text.strip():
                # 对话非空时，调用 LLM 执行摘要归档（允许隐藏记忆文件工具）。
                tool_defs_text = self.prompt_composer.render_tool_definitions_from_schema(self._list_tool_schemas())
                memory_token_limit = self._compression_memory_token_limit(thresholds)
                archive_messages = [
                    {
                        "role": "system",
                        "content": self.prompt_templates.compose_compression_system_prompt(
                            tool_definitions=tool_defs_text,
                            memory_file_path=f"employee/{employee_id}/.memory/{COMPRESSED_MEMORY_FILE}",
                            memory_token_limit=memory_token_limit,
                        ),
                    },
                    {"role": "user", "content": f"以下是待归档对话记录：\n\n{dialogue_text}"},
                ]
                archive_result = await self.agent_engine.process(
                    user_id=user_id,
                    employee_id=employee_id,
                    session_id=session_id,
                    messages=archive_messages,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                    allow_hidden_memory_files=True,
                )
                summary_text = archive_result.assistant_text.strip() or summary_text

            async with lock:
                # 按预算回收最近对话，同时把压缩期 buffer 迁回 dialogue。
                latest_dialogue_desc = await self.message_repo.list_messages(
                    user_id,
                    session_id,
                    zones=["dialogue"],
                    roles=["user", "assistant"],
                    message_kinds=["chat"],
                    ascending=False,
                    limit=5000,
                )
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

                # 清空后重建两个分区：resident_recent（保留上下文）+ dialogue（承接压缩期增量）。
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
                await self.session_repo.set_is_compressing(user_id, session_id, False)
        except Exception:  # noqa: BLE001
            # 任意异常都必须回收压缩标记，防止会话被永久锁死在压缩态。
            async with lock:
                await self.session_repo.set_is_compressing(user_id, session_id, False)
            raise

    async def execute_manual_compression(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        llm_config: LLMConfig,
    ) -> CompressionResult:
        """执行手动压缩并返回当前压缩状态。"""
        accepted = await self.try_start_manual_compression(user_id=user_id, session_id=session_id)
        if accepted:
            await self.compress_session_memory(
                user_id=user_id,
                employee_id=employee_id,
                session_id=session_id,
                llm_config=llm_config,
            )
        status = await self.get_memory_status(user_id, employee_id, session_id, llm_config.model)
        return CompressionResult(
            accepted=accepted,
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            is_compressing=status.is_compressing,
        )
