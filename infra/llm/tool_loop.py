"""工具调用循环处理与事件回传逻辑。"""

from __future__ import annotations

import inspect
from typing import Any

from app.ports.repositories import EventCallback, SystemMessageRefresher
from domain.models import LLMConfig
from infra.llm.event_publisher import emit, record_event
from infra.llm.request_builder import normalize_tool_name, serialize_tool_content
from infra.tools.builtin_tools import BuiltinToolRunner
from infra.tools.tool_registry import parse_tool_arguments


def replace_system_message(messages: list[dict[str, Any]], system_text: str) -> None:
    """替换消息列表中的 system 消息；不存在则插入到首位。"""
    for message in messages:
        if str(message.get("role", "")).strip() == "system":
            message["content"] = system_text
            return
    messages.insert(0, {"role": "system", "content": system_text})


async def refresh_system_message_after_memory_write(
    *,
    working_messages: list[dict[str, Any]],
    refresher: SystemMessageRefresher | None,
    round_index: int,
    tool_call_id: str,
    tool_args: dict[str, Any],
    on_event: EventCallback | None,
    tool_events: list[dict[str, Any]],
) -> None:
    """在写入记忆文件后刷新 system 提示词，并发出状态刷新事件。"""
    if refresher is None:
        return

    # refresher 允许同步/异步两种形式，这里统一兼容。
    refreshed = refresher()
    if inspect.isawaitable(refreshed):
        refreshed = await refreshed
    refreshed_text = str(refreshed or "")
    replace_system_message(working_messages, refreshed_text)

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
    await emit(refresh_event, on_event)


def append_tool_result_message(
    *,
    working_messages: list[dict[str, Any]],
    tool_call_id: str,
    tool_name: str,
    payload_result: dict[str, Any],
) -> None:
    """将工具执行结果以 tool 消息形式追加到工作消息列表。"""
    working_messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": serialize_tool_content(payload_result),
        }
    )


def build_tool_call_event(
    *,
    round_index: int,
    tool_call_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    assistant_tool_content: str,
    tool_call_index: int,
) -> dict[str, Any]:
    """构建工具调用事件（tool_call）。"""
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


def build_tool_result_event(
    *,
    round_index: int,
    tool_call_id: str,
    tool_name: str,
    payload_result: dict[str, Any],
) -> dict[str, Any]:
    """构建工具结果事件（tool_result）。"""
    return {
        "event": "tool_result",
        "round": round_index + 1,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "result": payload_result,
    }


async def process_tool_calls(
    *,
    round_index: int,
    normalized_tool_calls: list[dict[str, Any]],
    assistant_tool_content: str,
    user_id: str,
    employee_id: str,
    tool_runner: BuiltinToolRunner,
    llm_config: LLMConfig | None,
    working_messages: list[dict[str, Any]],
    on_event: EventCallback | None,
    tool_events: list[dict[str, Any]],
    refresh_system_message: SystemMessageRefresher | None,
) -> None:
    """依次执行模型返回的工具调用并回填工具结果消息。"""
    for tool_call_index, tool_call in enumerate(normalized_tool_calls):
        tool_name = normalize_tool_name(
            tool_call["function"].get("name", ""),
            fallback_suffix=tool_call["id"],
        )
        tool_call_id = tool_call["id"]
        raw_arguments = tool_call["function"].get("arguments", "{}")
        try:
            tool_args = parse_tool_arguments(raw_arguments)
        except Exception as exc:  # noqa: BLE001
            # 参数解析失败时也要写入 tool_call/tool_result 事件，
            # 保证上层事件流与消息回放链路完整。
            tool_args = {"_raw": raw_arguments}
            tool_call_event = build_tool_call_event(
                round_index=round_index,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
                assistant_tool_content=assistant_tool_content,
                tool_call_index=tool_call_index,
            )
            await record_event(tool_call_event, tool_events=tool_events, callback=on_event)

            error_payload = {"error": f"工具参数解析失败：{exc}"}
            tool_result_event = build_tool_result_event(
                round_index=round_index,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                payload_result=error_payload,
            )
            await record_event(tool_result_event, tool_events=tool_events, callback=on_event)
            append_tool_result_message(
                working_messages=working_messages,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                payload_result=error_payload,
            )
            continue

        tool_call_event = build_tool_call_event(
            round_index=round_index,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            assistant_tool_content=assistant_tool_content,
            tool_call_index=tool_call_index,
        )
        await record_event(tool_call_event, tool_events=tool_events, callback=on_event)

        try:
            tool_result = await tool_runner.execute(
                tool_name,
                tool_args,
                user_id=user_id,
                employee_id=employee_id,
                llm_config=llm_config,
            )
            payload_result: dict[str, Any] = {"result": tool_result}
        except Exception as exc:  # noqa: BLE001
            # 工具执行异常转换为 error payload，避免中断整轮对话。
            payload_result = {"error": f"工具执行失败：{exc}"}

        tool_result_event = build_tool_result_event(
            round_index=round_index,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            payload_result=payload_result,
        )
        await record_event(tool_result_event, tool_events=tool_events, callback=on_event)
        append_tool_result_message(
            working_messages=working_messages,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            payload_result=payload_result,
        )
        if tool_name == "write_memory_file" and "error" not in payload_result:
            # 记忆文件写成功后，下一轮模型应看到最新的 system 上下文。
            await refresh_system_message_after_memory_write(
                working_messages=working_messages,
                refresher=refresh_system_message,
                round_index=round_index,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
                on_event=on_event,
                tool_events=tool_events,
            )
