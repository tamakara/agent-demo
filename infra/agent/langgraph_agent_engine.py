"""基于 LangGraph 的 Agent 核心循环实现。

本模块承载以下职责：
1. 把应用层传入的消息转换为 LangChain/LangGraph 可执行消息对象。
2. 通过 ``StateGraph`` 组织“推理 -> 工具 -> 推理”的循环流程。
3. 使用 ``add_messages`` reducer 管理消息状态，避免手工 append 拼接。
4. 统一输出可观测事件（graph_*），供 SSE 与调试落库使用。
5. 以 ``MemorySaver`` + ``thread_id/checkpoint_ns`` 实现按会话、按请求隔离的图内状态。
"""

from __future__ import annotations

import json
import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Annotated, Literal, TypedDict
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field, create_model

from app.interfaces import (
    EventCallback,
    IAgentEngine,
    IToolRunner,
    SystemMessageRefresher,
)
from domain.models import LLMConfig, LLMRunResult
from infra.agent.openai_base_url import normalize_openai_base_url
from infra.agent.tools.tool_registry import TOOL_SCHEMAS


SYSTEM_MESSAGE_ID = "resident_system"


class AgentState(TypedDict, total=False):
    """图运行状态。

    字段说明：
    - ``messages``：当前图上下文消息，使用 ``add_messages`` 进行归并。
    - ``round_count``：已完成的推理轮次计数（reasoning 节点执行次数）。
    - ``max_tool_rounds``：本次调用允许的最大工具轮次。
    - ``reached_tool_limit``：是否触发工具轮次上限兜底。
    - ``should_refresh_system``：工具写入记忆后，下一轮是否刷新 system。
    - ``usage``：模型侧 usage 信息（若可提取）。
    """

    messages: Annotated[list[BaseMessage], add_messages]
    round_count: int
    max_tool_rounds: int
    reached_tool_limit: bool
    should_refresh_system: bool
    usage: dict[str, Any] | None


@dataclass(slots=True)
class _RuntimeContext:
    """单次 process 调用的运行时上下文。

    使用 ``ContextVar`` 保存，确保图节点可以读取调用级依赖，
    同时避免把大量运行时对象塞进 Graph State。
    """

    user_id: str
    employee_id: str
    session_id: str
    llm_config: LLMConfig
    max_tool_rounds: int
    allow_hidden_memory_files: bool
    on_event: EventCallback | None
    refresh_system_message: SystemMessageRefresher | None
    turn_ns: str
    bound_model: Any
    tool_events: list[dict[str, Any]]


class LangGraphAgentEngine(IAgentEngine):
    """基于 LangGraph + ToolNode 的 Agent 引擎实现。

    设计目标：
    - 应用层只依赖接口，不感知 LangGraph。
    - 工具循环全部交给图路由和 ToolNode，移除手写 while/for 解析逻辑。
    - 事件流统一、可观测，便于前端展示和服务端排障。
    """

    def __init__(self, *, tool_runner: IToolRunner) -> None:
        """初始化图组件与工具绑定。

        关键对象：
        - ``_tools``：由既有 TOOL_SCHEMAS 动态构建的 LangChain 工具列表。
        - ``_tool_node``：LangGraph 内置工具执行节点，包含异常兜底能力。
        - ``_checkpointer``：内存检查点，用于同次调用中的状态快照与恢复。
        """
        self.tool_runner = tool_runner
        self._runtime_ctx: ContextVar[_RuntimeContext | None] = ContextVar(
            "langgraph_runtime_context",
            default=None,
        )
        self._tool_schemas: list[dict[str, Any]] = [dict(item) for item in TOOL_SCHEMAS]
        self._tools = self._build_langchain_tools()
        self._tool_node = ToolNode(self._tools, handle_tool_errors=True)
        self._checkpointer = MemorySaver()
        self._graph = self._build_graph()

    async def process(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
        refresh_system_message: SystemMessageRefresher | None = None,
        allow_hidden_memory_files: bool = False,
    ) -> LLMRunResult:
        """执行一次完整图调用并返回应用层统一结果。

        流程概览：
        1. 组装调用级 runtime context（身份、模型、回调、轮次限制）。
        2. 构建初始 AgentState，并设置 ``thread_id + checkpoint_ns``。
        3. 调用编译后的 graph 执行状态流转。
        4. 提取最终 assistant 文本、usage、事件和工作消息快照。
        """
        turn_ns = uuid4().hex
        runtime = _RuntimeContext(
            user_id=user_id,
            employee_id=employee_id,
            session_id=session_id,
            llm_config=llm_config,
            max_tool_rounds=max(1, int(max_tool_rounds or 1)),
            allow_hidden_memory_files=allow_hidden_memory_files,
            on_event=on_event,
            refresh_system_message=refresh_system_message,
            turn_ns=turn_ns,
            bound_model=self._create_bound_model(llm_config),
            tool_events=[],
        )
        token = self._runtime_ctx.set(runtime)
        try:
            initial_state: AgentState = {
                "messages": self._to_base_messages(messages),
                "round_count": 0,
                "max_tool_rounds": runtime.max_tool_rounds,
                "reached_tool_limit": False,
                "should_refresh_system": False,
                "usage": None,
            }
            config = {
                "configurable": {
                    "thread_id": session_id,
                    # 每次请求使用独立命名空间，避免不同请求共享图内历史。
                    "checkpoint_ns": turn_ns,
                }
            }
            final_state = await self._graph.ainvoke(initial_state, config=config)
            final_messages = list(final_state.get("messages", []))
            final_text = self._extract_final_assistant_text(final_messages, runtime.tool_events)
            usage = final_state.get("usage")
            if usage is not None and not isinstance(usage, dict):
                usage = {"value": str(usage)}

            return LLMRunResult(
                assistant_text=final_text,
                tool_events=list(runtime.tool_events),
                usage=usage,
                working_messages=self._messages_to_dict(final_messages),
                reached_tool_limit=bool(final_state.get("reached_tool_limit", False)),
            )
        finally:
            self._runtime_ctx.reset(token)

    def _build_graph(self):
        """构建并编译状态图。

        路由规则：
        - START -> reasoning
        - reasoning 返回 tool_calls -> tools
        - reasoning 无 tool_calls 或触发轮次上限 -> END
        - tools 执行完成 -> reasoning
        """
        graph = StateGraph(AgentState)
        graph.add_node("reasoning", self._reasoning_node)
        graph.add_node("tools", self._tools_node)
        graph.add_edge(START, "reasoning")
        graph.add_conditional_edges(
            "reasoning",
            self._route_after_reasoning,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "reasoning")
        return graph.compile(checkpointer=self._checkpointer)

    def _create_bound_model(self, llm_config: LLMConfig) -> Any:
        """创建并返回绑定工具后的 ChatOpenAI 模型对象。"""
        extra_body = self._resolve_chat_extra_body(llm_config)
        model = ChatOpenAI(
            api_key=llm_config.api_key,
            base_url=normalize_openai_base_url(llm_config.base_url),
            model=llm_config.model,
            timeout=120.0,
            temperature=1.0,
            extra_body=extra_body,
        )
        return model.bind_tools(self._tool_schemas)

    @staticmethod
    def _resolve_chat_extra_body(llm_config: LLMConfig) -> dict[str, Any] | None:
        """根据用户配置生成 Chat 请求额外参数。

        当前策略：
        - ``deep_thinking_enabled=False``（默认）时，显式关闭 thinking；
        - ``deep_thinking_enabled=True`` 时，不注入禁用参数，让模型按默认行为思考。
        """
        if not bool(getattr(llm_config, "deep_thinking_enabled", False)):
            return {"thinking": {"type": "disabled"}}
        return None

    async def _reasoning_node(self, state: AgentState) -> AgentState:
        """推理节点：调用模型、产出 AIMessage、决定是否继续工具分支。"""
        runtime = self._require_runtime()
        messages = list(state.get("messages", []))
        round_index = int(state.get("round_count", 0)) + 1
        messages_update: list[BaseMessage] = []

        if state.get("should_refresh_system", False):
            # 工具写记忆成功后，下一轮推理前刷新 system，确保模型看到最新记忆。
            refreshed_text = await self._refresh_system_message_if_needed(runtime)
            if refreshed_text:
                self._replace_system_message(messages, refreshed_text)
                messages_update.append(SystemMessage(content=refreshed_text, id=SYSTEM_MESSAGE_ID))

        await self._emit_event(
            runtime,
            {
                "event": "graph_reasoning_start",
                "round": round_index,
                "message_count": len(messages),
            },
        )

        try:
            response = await runtime.bound_model.ainvoke(messages)
        except Exception as exc:  # noqa: BLE001
            await self._emit_event(
                runtime,
                {
                    "event": "graph_error",
                    "stage": "reasoning",
                    "round": round_index,
                    "error": str(exc),
                },
            )
            raise RuntimeError(f"模型调用失败：{exc}") from exc

        if not isinstance(response, AIMessage):
            response = AIMessage(content=self._coerce_text(response))

        usage = self._extract_usage(response)
        has_tool_calls = bool(response.tool_calls)
        tool_call_count = len(response.tool_calls)
        reached_tool_limit = bool(state.get("reached_tool_limit", False))
        effective_message: AIMessage = response
        max_tool_rounds = int(state.get("max_tool_rounds", runtime.max_tool_rounds))

        if has_tool_calls and round_index >= max_tool_rounds:
            # 到达工具轮次上限时，强制终止工具分支并返回可读兜底文案。
            reached_tool_limit = True
            effective_message = AIMessage(content=self._tool_round_limit_text(max_tool_rounds))
            has_tool_calls = False
            tool_call_count = 0
            await self._emit_event(
                runtime,
                {
                    "event": "graph_error",
                    "stage": "routing",
                    "round": round_index,
                    "error": "max_tool_rounds_reached",
                    "max_tool_rounds": max_tool_rounds,
                },
            )

        await self._emit_event(
            runtime,
            {
                "event": "graph_reasoning_end",
                "round": round_index,
                "has_tool_calls": has_tool_calls,
                "tool_call_count": tool_call_count,
                "content_length": len(self._coerce_text(effective_message.content).strip()),
                "usage": usage or {},
            },
        )

        return {
            "messages": [*messages_update, effective_message],
            "round_count": round_index,
            "reached_tool_limit": reached_tool_limit,
            "should_refresh_system": False,
            "usage": usage,
        }

    async def _tools_node(self, state: AgentState, config: RunnableConfig) -> AgentState:
        """工具节点：执行本轮工具调用并回写 ToolMessage。"""
        runtime = self._require_runtime()
        latest_ai = self._last_ai_message(state.get("messages", []))
        round_index = int(state.get("round_count", 0))
        pending_calls: dict[str, dict[str, Any]] = {}

        raw_tool_calls = list((latest_ai.tool_calls if latest_ai is not None else []) or [])
        for call_index, tool_call in enumerate(raw_tool_calls):
            # 先发出 graph_tool_start，便于外层实时展示“正在调用哪个工具”。
            tool_call_id = str(tool_call.get("id") or f"tool_call_{round_index}_{call_index}")
            tool_name = str(tool_call.get("name") or "").strip()
            tool_args = tool_call.get("args", {})
            if not isinstance(tool_args, dict):
                tool_args = {"_raw": tool_args}

            pending_calls[tool_call_id] = {"tool_name": tool_name, "arguments": tool_args}
            await self._emit_event(
                runtime,
                {
                    "event": "graph_tool_start",
                    "round": round_index,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                },
            )

        tool_output = await self._tool_node.ainvoke(state, config=config)
        result_messages = list(tool_output.get("messages", []))
        should_refresh_system = False

        for message in result_messages:
            if not isinstance(message, ToolMessage):
                continue
            tool_call_id = str(message.tool_call_id or "")
            mapped = pending_calls.get(tool_call_id, {})
            tool_name = str(mapped.get("tool_name") or getattr(message, "name", "") or "").strip()
            result_text = self._coerce_text(message.content)
            status = str(getattr(message, "status", "success") or "success").strip().lower()
            is_error = status == "error"
            payload_result: dict[str, Any] = {"error": result_text} if is_error else {"result": result_text}

            await self._emit_event(
                runtime,
                {
                    "event": "graph_tool_end",
                    "round": round_index,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "status": "error" if is_error else "ok",
                    "result": payload_result,
                },
            )
            if tool_name == "write_memory_file" and not is_error:
                # 仅在写记忆成功时标记刷新，避免失败结果覆盖有效 system。
                should_refresh_system = True

        return {
            "messages": result_messages,
            "should_refresh_system": should_refresh_system,
        }

    def _route_after_reasoning(self, state: AgentState) -> Literal["tools", "end"]:
        """根据最新 AIMessage 是否包含工具调用决定下一跳。"""
        if bool(state.get("reached_tool_limit", False)):
            return "end"
        latest_ai = self._last_ai_message(state.get("messages", []))
        if latest_ai is not None and latest_ai.tool_calls:
            return "tools"
        return "end"

    def _build_langchain_tools(self) -> list[StructuredTool]:
        """根据 TOOL_SCHEMAS 动态构建 LangChain StructuredTool 列表。"""
        tools: list[StructuredTool] = []
        for schema in self._tool_schemas:
            function_spec = schema.get("function", {})
            if not isinstance(function_spec, dict):
                continue
            tool_name = str(function_spec.get("name", "")).strip()
            if not tool_name:
                continue
            description = str(function_spec.get("description", "")).strip() or tool_name
            parameters = function_spec.get("parameters", {})
            args_schema = self._build_args_schema(tool_name=tool_name, parameters=parameters)

            async def _tool_coroutine(_tool_name: str = tool_name, **kwargs: Any) -> str:
                # 统一回落到既有 IToolRunner，保证工具权限与业务规则不漂移。
                runtime = self._require_runtime()
                return await self.tool_runner.execute(
                    _tool_name,
                    kwargs,
                    user_id=runtime.user_id,
                    employee_id=runtime.employee_id,
                    llm_config=runtime.llm_config,
                    allow_hidden_memory_files=runtime.allow_hidden_memory_files,
                )

            tools.append(
                StructuredTool.from_function(
                    coroutine=_tool_coroutine,
                    name=tool_name,
                    description=description,
                    args_schema=args_schema,
                )
            )
        return tools

    @staticmethod
    def _json_schema_to_python_type(schema: dict[str, Any]) -> Any:
        """把 JSON Schema 基础类型映射为 Python 注解类型。"""
        schema_type = str(schema.get("type", "")).strip().lower()
        if schema_type == "string":
            return str
        if schema_type == "integer":
            return int
        if schema_type == "number":
            return float
        if schema_type == "boolean":
            return bool
        if schema_type == "array":
            items = schema.get("items", {})
            if isinstance(items, dict):
                item_type = LangGraphAgentEngine._json_schema_to_python_type(items)
            else:
                item_type = Any
            return list[item_type]
        if schema_type == "object":
            return dict[str, Any]
        return Any

    def _build_args_schema(self, *, tool_name: str, parameters: Any) -> type[BaseModel]:
        """基于工具参数定义构建 Pydantic 参数模型。

        目的：让 ToolNode 在执行前获得结构化参数校验能力。
        """
        if not isinstance(parameters, dict):
            return create_model(f"{tool_name.title()}Args")
        properties = parameters.get("properties", {})
        required = set(parameters.get("required", [])) if isinstance(parameters.get("required"), list) else set()
        if not isinstance(properties, dict):
            return create_model(f"{tool_name.title()}Args")

        fields: dict[str, Any] = {}
        for field_name, spec in properties.items():
            if not isinstance(spec, dict):
                continue
            python_type = self._json_schema_to_python_type(spec)
            description = str(spec.get("description", "")).strip() or None
            if field_name in required:
                fields[field_name] = (python_type, Field(..., description=description))
            else:
                fields[field_name] = (python_type | None, Field(default=None, description=description))
        return create_model(f"{tool_name.title()}Args", **fields)

    @staticmethod
    def _tool_round_limit_text(max_tool_rounds: int) -> str:
        """生成工具轮次超限时返回给用户的兜底提示。"""
        return (
            f"工具调用超过最大轮次限制（{max_tool_rounds}），已中止本次调用。"
            "请收敛工具调用步骤后重试。"
        )

    def _extract_final_assistant_text(
        self,
        messages: list[BaseMessage],
        tool_events: list[dict[str, Any]],
    ) -> str:
        """从最终消息序列提取可展示的 assistant 文本。

        规则：
        - 逆序查找最后一个不含 tool_calls 的 AIMessage。
        - 若找不到文本，则根据工具事件构造可读兜底文案。
        """
        for message in reversed(messages):
            if not isinstance(message, AIMessage):
                continue
            if message.tool_calls:
                continue
            text = self._coerce_text(message.content).strip()
            if text:
                return text
        return self._build_empty_final_text(tool_events)

    @staticmethod
    def _build_empty_final_text(tool_events: list[dict[str, Any]]) -> str:
        """模型空文本时，按事件上下文构造错误提示。"""
        latest_error = ""
        has_tool_activity = False
        for event in reversed(tool_events):
            event_name = str(event.get("event", "")).strip()
            if event_name == "graph_tool_end":
                has_tool_activity = True
                payload = event.get("result")
                if isinstance(payload, dict):
                    error_text = str(payload.get("error", "")).strip()
                    if error_text:
                        latest_error = error_text
                        break
            if event_name == "graph_tool_start":
                has_tool_activity = True
        if latest_error:
            return f"模型未返回有效文本结果。最近一次工具执行失败：{latest_error}"
        if has_tool_activity:
            return "模型未返回有效文本结果。工具已执行，但未产出最终答复，请重试。"
        return "模型未返回有效文本结果，且未发起工具调用，请重试或切换更稳定的工具模型。"

    @staticmethod
    def _extract_usage(message: AIMessage) -> dict[str, Any] | None:
        """从 AIMessage 提取 usage 字段，兼容不同 SDK 返回形态。"""
        usage = getattr(message, "usage_metadata", None)
        if isinstance(usage, dict):
            return dict(usage)
        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict):
            token_usage = response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                return dict(token_usage)
            usage = response_metadata.get("usage")
            if isinstance(usage, dict):
                return dict(usage)
        return None

    async def _refresh_system_message_if_needed(self, runtime: _RuntimeContext) -> str:
        """按需执行 system 刷新器，兼容同步/异步两种回调。"""
        refresher = runtime.refresh_system_message
        if refresher is None:
            return ""
        refreshed = refresher()
        if inspect.isawaitable(refreshed):
            refreshed = await refreshed
        return str(refreshed or "")

    @staticmethod
    def _replace_system_message(messages: list[BaseMessage], refreshed_text: str) -> None:
        """就地替换 system 消息；若不存在则插入到首位。"""
        for idx, message in enumerate(messages):
            if isinstance(message, SystemMessage):
                current_id = getattr(message, "id", None) or SYSTEM_MESSAGE_ID
                messages[idx] = SystemMessage(content=refreshed_text, id=str(current_id))
                return
        messages.insert(0, SystemMessage(content=refreshed_text, id=SYSTEM_MESSAGE_ID))

    def _require_runtime(self) -> _RuntimeContext:
        """读取当前调用上下文；缺失时抛错避免静默失败。"""
        runtime = self._runtime_ctx.get()
        if runtime is None:
            raise RuntimeError("LangGraph runtime context is missing")
        return runtime

    async def _emit_event(self, runtime: _RuntimeContext, event: dict[str, Any]) -> None:
        """统一事件出口：先写入本地事件，再转发到外部回调。"""
        runtime.tool_events.append(event)
        callback = runtime.on_event
        if callback is None:
            return
        maybe_coro = callback(event)
        if maybe_coro is not None:
            await maybe_coro

    @staticmethod
    def _last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
        """逆序获取最后一个 AIMessage。"""
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                return message
        return None

    def _to_base_messages(self, messages: list[dict[str, Any]]) -> list[BaseMessage]:
        """把应用层字典消息转换为 LangChain BaseMessage 列表。"""
        base_messages: list[BaseMessage] = []
        has_primary_system = False
        for raw in messages:
            role = str(raw.get("role", "")).strip().lower()
            content = self._coerce_text(raw.get("content"))

            if role == "system":
                # 第一条 system 固定打上 resident id，便于后续精确替换。
                message_id = str(raw.get("id", "")).strip() or (SYSTEM_MESSAGE_ID if not has_primary_system else None)
                has_primary_system = True
                if message_id:
                    base_messages.append(SystemMessage(content=content, id=message_id))
                else:
                    base_messages.append(SystemMessage(content=content))
                continue

            if role == "user":
                base_messages.append(HumanMessage(content=content))
                continue

            if role == "tool":
                tool_call_id = str(raw.get("tool_call_id", "")).strip()
                if not tool_call_id:
                    continue
                name = str(raw.get("name", "")).strip() or None
                if name:
                    base_messages.append(
                        ToolMessage(content=content, tool_call_id=tool_call_id, name=name)
                    )
                else:
                    base_messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
                continue

            base_messages.append(AIMessage(content=content))

        if not has_primary_system:
            # 兜底：确保图内始终有 system 位，后续刷新逻辑可稳定工作。
            base_messages.insert(0, SystemMessage(content="", id=SYSTEM_MESSAGE_ID))
        return base_messages

    def _messages_to_dict(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        """把 BaseMessage 序列列化回应用层字典结构。"""
        rows: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                rows.append({"role": "system", "content": self._coerce_text(message.content)})
                continue
            if isinstance(message, HumanMessage):
                rows.append({"role": "user", "content": self._coerce_text(message.content)})
                continue
            if isinstance(message, ToolMessage):
                row = {
                    "role": "tool",
                    "content": self._coerce_text(message.content),
                    "tool_call_id": str(message.tool_call_id or ""),
                }
                tool_name = str(getattr(message, "name", "") or "").strip()
                if tool_name:
                    row["name"] = tool_name
                rows.append(row)
                continue
            if isinstance(message, AIMessage):
                if message.tool_calls:
                    tool_calls: list[dict[str, Any]] = []
                    for call in message.tool_calls:
                        tool_calls.append(
                            {
                                "id": str(call.get("id", "")),
                                "type": "function",
                                "function": {
                                    "name": str(call.get("name", "")),
                                    "arguments": json.dumps(call.get("args", {}), ensure_ascii=False),
                                },
                            }
                        )
                    rows.append(
                        {
                            "role": "assistant",
                            "content": self._coerce_text(message.content) or None,
                            "tool_calls": tool_calls,
                        }
                    )
                else:
                    rows.append({"role": "assistant", "content": self._coerce_text(message.content)})
                continue

            rows.append({"role": "assistant", "content": self._coerce_text(getattr(message, "content", ""))})
        return rows

    @staticmethod
    def _coerce_text(content: Any) -> str:
        """把多形态 content 统一压平成字符串文本。"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(str(item.get("text", "")))
                else:
                    chunks.append(str(item))
            return "".join(chunks)
        return str(content)
