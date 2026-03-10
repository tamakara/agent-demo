"""基于 OpenAI AsyncOpenAI SDK 的工具调用循环实现。"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from core.models import LLMConfig
from core.tools import TOOL_SCHEMAS, execute_tool_call, parse_tool_arguments


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
SystemMessageRefresher = Callable[[], Awaitable[str] | str]
OPENAI_DEFAULT_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
OPENAI_SUFFIX_CHAT_COMPLETIONS = "/chat/completions"
FALLBACK_TOOL_NAME_PREFIX = "unknown_tool"


@dataclass(slots=True)
class AgentRunResult:
    """单次 agent 运行结果。"""

    assistant_text: str
    tool_events: list[dict[str, Any]]
    usage: dict[str, Any] | None
    working_messages: list[dict[str, Any]]
    reached_tool_limit: bool = False


def _coerce_content(content: Any) -> str:
    """把 OpenAI message.content 统一转换为纯文本字符串。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    chunks.append(str(item.get("text", "")))
                else:
                    chunks.append(str(item))
            else:
                chunks.append(str(item))
        return "".join(chunks)
    return str(content)


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """兼容不同 SDK 对 usage 的返回形态。"""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    if hasattr(usage, "model_dump"):
        dumped = usage.model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    return {"value": str(usage)}


def _normalize_tool_name(name: Any, fallback_suffix: str) -> str:
    """归一化工具名；空名称时生成可追踪兜底名。"""
    candidate = str(name or "").strip()
    if candidate:
        return candidate
    return f"{FALLBACK_TOOL_NAME_PREFIX}_{fallback_suffix}"


def _stringify_tool_arguments(raw_arguments: Any) -> str:
    """确保工具参数最终以字符串 JSON 形式传入模型历史。"""
    if isinstance(raw_arguments, str):
        return raw_arguments
    if raw_arguments is None:
        return "{}"
    if isinstance(raw_arguments, (dict, list)):
        return json.dumps(raw_arguments, ensure_ascii=False)
    return str(raw_arguments)


def _serialize_tool_content(payload: Any) -> str:
    """把工具结果对象序列化为 tool 消息 content。"""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        if "result" in payload and len(payload) == 1:
            return str(payload.get("result", ""))
        if "error" in payload and len(payload) == 1:
            return str(payload.get("error", ""))
        return json.dumps(payload, ensure_ascii=False)
    if isinstance(payload, list):
        return json.dumps(payload, ensure_ascii=False)
    if payload is None:
        return ""
    return str(payload)


def _normalize_tool_call(raw_tool_call: Any, fallback_id: str) -> dict[str, Any]:
    """把 SDK 返回的 tool_call 标准化为 OpenAI 协议结构。"""
    if hasattr(raw_tool_call, "model_dump"):
        raw_tool_call = raw_tool_call.model_dump()

    if isinstance(raw_tool_call, dict):
        function_data = raw_tool_call.get("function", {})
        if hasattr(function_data, "model_dump"):
            function_data = function_data.model_dump()
        if not isinstance(function_data, dict):
            function_data = {}
        normalized_id = str(raw_tool_call.get("id") or fallback_id)
        normalized_name = _normalize_tool_name(
            function_data.get("name", ""),
            fallback_suffix=normalized_id,
        )
        return {
            "id": normalized_id,
            "type": "function",
            "function": {
                "name": normalized_name,
                "arguments": _stringify_tool_arguments(function_data.get("arguments", "{}")),
            },
        }

    function_data = getattr(raw_tool_call, "function", None)
    name = ""
    arguments: Any = "{}"
    if function_data is not None:
        name = str(getattr(function_data, "name", ""))
        arguments = getattr(function_data, "arguments", "{}")
    normalized_id = str(getattr(raw_tool_call, "id", fallback_id))
    normalized_name = _normalize_tool_name(name, fallback_suffix=normalized_id)
    return {
        "id": normalized_id,
        "type": "function",
        "function": {
            "name": normalized_name,
            "arguments": _stringify_tool_arguments(arguments),
        },
    }


def _extract_message(response: Any) -> Any:
    """从 SDK 响应中提取首个 message。"""
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM 返回结果缺少 choices 字段")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise ValueError("LLM 返回结果缺少 message 字段")
    return message


async def _emit(event: dict[str, Any], callback: EventCallback | None) -> None:
    """向外发事件，兼容同步/异步回调。"""
    if callback is None:
        return
    maybe_coro = callback(event)
    if maybe_coro is not None:
        await maybe_coro


def _replace_system_message(messages: list[dict[str, Any]], system_text: str) -> None:
    """替换历史消息中的 system 消息；不存在则插入首位。"""
    for message in messages:
        if str(message.get("role", "")).strip() == "system":
            message["content"] = system_text
            return
    messages.insert(0, {"role": "system", "content": system_text})


async def _refresh_system_message_after_memory_write(
    *,
    working_messages: list[dict[str, Any]],
    refresher: SystemMessageRefresher | None,
    round_index: int,
    tool_call_id: str,
    tool_args: dict[str, Any],
    on_event: EventCallback | None,
    tool_events: list[dict[str, Any]],
) -> None:
    """write_memory_file 成功后刷新常驻 system 文本，并发送 state_refresh 事件。"""
    if refresher is None:
        return

    refreshed = refresher()
    if inspect.isawaitable(refreshed):
        refreshed = await refreshed
    refreshed_text = str(refreshed or "")
    _replace_system_message(working_messages, refreshed_text)

    file_name = str(tool_args.get("file_name", "")).strip()
    refresh_event: dict[str, Any] = {
        "event": "meta",
        "type": "state_refresh",
        "round": round_index + 1,
        "reason": "write_memory_file_success",
        "tool_call_id": tool_call_id,
    }
    if file_name:
        refresh_event["file_name"] = file_name
    tool_events.append(refresh_event)
    await _emit(refresh_event, on_event)


def _normalize_openai_base_url(base_url: str | None) -> str:
    """统一 base_url 形态（去尾斜杠、去 /chat/completions 后缀）。"""
    actual_base_url = (base_url or OPENAI_DEFAULT_BASE_URL).strip()
    if not actual_base_url:
        actual_base_url = OPENAI_DEFAULT_BASE_URL
    actual_base_url = actual_base_url.rstrip("/")
    if actual_base_url.endswith(OPENAI_SUFFIX_CHAT_COMPLETIONS):
        actual_base_url = actual_base_url[: -len(OPENAI_SUFFIX_CHAT_COMPLETIONS)]
    actual_base_url = actual_base_url.rstrip("/")
    if not actual_base_url:
        return OPENAI_DEFAULT_BASE_URL
    return actual_base_url


def _build_chat_completions_endpoint(base_url: str) -> str:
    """根据 base_url 计算完整 chat/completions endpoint。"""
    normalized = base_url.rstrip("/")
    return f"{normalized}/chat/completions"


async def _call_chat_completions(
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
    model: str,
) -> Any:
    """统一调用 OpenAI chat.completions 接口。"""
    typed_messages = cast(Iterable[ChatCompletionMessageParam], messages)
    typed_tools = cast(Iterable[ChatCompletionToolUnionParam], TOOL_SCHEMAS)
    return await client.chat.completions.create(
        model=model,
        messages=typed_messages,
        tools=typed_tools,
        tool_choice="auto",
    )


async def _record_event(
    event: dict[str, Any],
    *,
    tool_events: list[dict[str, Any]],
    callback: EventCallback | None,
) -> None:
    """保存并透传事件，避免每次都手写 append + emit。"""
    tool_events.append(event)
    await _emit(event, callback)


def _build_tool_call_event(
    *,
    round_index: int,
    tool_call_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    assistant_tool_content: str,
    tool_call_index: int,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event": "tool_call",
        "round": round_index + 1,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "arguments": tool_args,
    }
    if tool_call_index == 0 and assistant_tool_content:
        event["assistant_content"] = assistant_tool_content
    return event


def _build_tool_result_event(
    *,
    round_index: int,
    tool_call_id: str,
    tool_name: str,
    payload_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event": "tool_result",
        "round": round_index + 1,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "result": payload_result,
    }


def _append_tool_result_message(
    *,
    working_messages: list[dict[str, Any]],
    tool_call_id: str,
    tool_name: str,
    payload_result: dict[str, Any],
) -> None:
    """把工具执行结果追加到消息历史，供下一轮模型推理。"""
    working_messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": _serialize_tool_content(payload_result),
        }
    )


async def run_agent_with_tools(
    user_id: str,
    messages: list[dict[str, Any]],
    llm_config: LLMConfig,
    max_tool_rounds: int = 6,
    on_event: EventCallback | None = None,
    refresh_system_message: SystemMessageRefresher | None = None,
) -> AgentRunResult:
    """执行智能体循环，直到得到最终回复文本。"""

    working_messages = [dict(m) for m in messages]
    tool_events: list[dict[str, Any]] = []
    latest_usage: dict[str, Any] | None = None

    normalized_base_url = _normalize_openai_base_url(llm_config.base_url)
    endpoint_url = _build_chat_completions_endpoint(normalized_base_url)
    client = AsyncOpenAI(
        api_key=llm_config.api_key,
        base_url=normalized_base_url,
        timeout=120.0,
    )
    try:
        for round_index in range(max_tool_rounds):
            # 每轮先记录完整请求快照，便于前端和日志系统追踪排障。
            request_body = {
                "model": llm_config.model,
                "messages": working_messages,
                "tools": TOOL_SCHEMAS,
                "tool_choice": "auto",
            }
            request_snapshot = json.loads(json.dumps(request_body, ensure_ascii=False))
            llm_request_event = {
                "event": "meta",
                "type": "llm_request",
                "user_id": user_id,
                "round": round_index + 1,
                "llm_api": {
                    "sdk": "openai.AsyncOpenAI",
                    "method": "POST",
                    "base_url": normalized_base_url,
                    "endpoint": endpoint_url,
                },
                "request_body": request_snapshot,
            }
            await _record_event(llm_request_event, tool_events=tool_events, callback=on_event)

            try:
                response = await _call_chat_completions(
                    client=client,
                    messages=working_messages,
                    model=llm_config.model,
                )
            except APIStatusError as exc:
                raise RuntimeError(f"模型接口调用失败（HTTP {exc.status_code}）：{exc}") from exc
            except APITimeoutError as exc:
                raise RuntimeError(f"模型接口连接超时：{exc}") from exc
            except APIConnectionError as exc:
                raise RuntimeError(f"模型接口连接失败：{exc}") from exc
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"模型接口调用异常：{exc}") from exc

            latest_usage = _extract_usage(response)
            message = _extract_message(response)
            content = _coerce_content(getattr(message, "content", None))
            raw_tool_calls = getattr(message, "tool_calls", None) or []
            normalized_tool_calls = [
                _normalize_tool_call(call, fallback_id=f"tool_call_{round_index}_{idx}")
                for idx, call in enumerate(raw_tool_calls)
            ]

            if normalized_tool_calls:
                assistant_tool_content = content.strip()
                working_messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_tool_content or None,
                        "tool_calls": normalized_tool_calls,
                    }
                )
                for tool_call_index, tool_call in enumerate(normalized_tool_calls):
                    tool_name = _normalize_tool_name(
                        tool_call["function"].get("name", ""),
                        fallback_suffix=tool_call["id"],
                    )
                    tool_call_id = tool_call["id"]
                    raw_arguments = tool_call["function"].get("arguments", "{}")
                    try:
                        tool_args = parse_tool_arguments(raw_arguments)
                    except Exception as exc:  # noqa: BLE001
                        tool_args = {"_raw": raw_arguments}
                        tool_call_event = _build_tool_call_event(
                            round_index=round_index,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            assistant_tool_content=assistant_tool_content,
                            tool_call_index=tool_call_index,
                        )
                        await _record_event(tool_call_event, tool_events=tool_events, callback=on_event)

                        error_payload = {"error": f"工具参数解析失败：{exc}"}
                        tool_result_event = _build_tool_result_event(
                            round_index=round_index,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            payload_result=error_payload,
                        )
                        await _record_event(tool_result_event, tool_events=tool_events, callback=on_event)
                        _append_tool_result_message(
                            working_messages=working_messages,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            payload_result=error_payload,
                        )
                        continue

                    tool_call_event = _build_tool_call_event(
                        round_index=round_index,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        assistant_tool_content=assistant_tool_content,
                        tool_call_index=tool_call_index,
                    )
                    await _record_event(tool_call_event, tool_events=tool_events, callback=on_event)

                    try:
                        tool_result = await execute_tool_call(tool_name, tool_args, user_id=user_id)
                        payload_result: dict[str, Any] = {"result": tool_result}
                    except Exception as exc:  # noqa: BLE001
                        payload_result = {"error": f"工具执行失败：{exc}"}

                    tool_result_event = _build_tool_result_event(
                        round_index=round_index,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        payload_result=payload_result,
                    )
                    await _record_event(tool_result_event, tool_events=tool_events, callback=on_event)
                    _append_tool_result_message(
                        working_messages=working_messages,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        payload_result=payload_result,
                    )
                    if tool_name == "write_memory_file" and "error" not in payload_result:
                        await _refresh_system_message_after_memory_write(
                            working_messages=working_messages,
                            refresher=refresh_system_message,
                            round_index=round_index,
                            tool_call_id=tool_call_id,
                            tool_args=tool_args,
                            on_event=on_event,
                            tool_events=tool_events,
                        )
                continue

            final_text = content.strip()
            working_messages.append({"role": "assistant", "content": final_text})
            return AgentRunResult(
                assistant_text=final_text,
                tool_events=tool_events,
                usage=latest_usage,
                working_messages=working_messages,
                reached_tool_limit=False,
            )
    finally:
        await client.close()

    fallback_text = (
        f"工具调用超过最大轮次限制（{max_tool_rounds}），已中止本次调用。"
        "请收敛工具调用步骤后重试。"
    )
    return AgentRunResult(
        assistant_text=fallback_text,
        tool_events=tool_events,
        usage=latest_usage,
        working_messages=working_messages,
        reached_tool_limit=True,
    )
