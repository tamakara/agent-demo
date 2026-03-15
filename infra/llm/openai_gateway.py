"""OpenAI 网关适配与多轮工具调用驱动。"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from app.ports.repositories import EventCallback, LLMGatewayPort, SystemMessageRefresher
from domain.models import LLMConfig, LLMRunResult
from infra.llm.event_publisher import record_event
from infra.llm.request_builder import (
    build_chat_completions_endpoint,
    build_typed_messages,
    build_typed_tools,
    coerce_content,
    extract_kimi_markup_tool_calls,
    extract_message,
    extract_raw_tool_calls,
    extract_usage,
    normalize_openai_base_url,
    normalize_tool_call,
    strip_kimi_tool_markup,
)
from infra.llm.tool_loop import process_tool_calls
from infra.tools.builtin_tools import BuiltinToolRunner
from infra.tools.tool_registry import TOOL_SCHEMAS


DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_COMPLETION_TOKENS = 64000
DEFAULT_PARALLEL_TOOL_CALLS = False
DEFAULT_REASONING_EFFORT = "high"


def extract_finish_reason(response: Any) -> str:
    """提取首个 choice 的 finish_reason。"""
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    finish_reason = getattr(first_choice, "finish_reason", None)
    if finish_reason is None and isinstance(first_choice, dict):
        finish_reason = first_choice.get("finish_reason")
    return str(finish_reason or "").strip()


def extract_tool_name(raw_tool_calls: list[dict[str, Any]]) -> str:
    """提取首个工具名。"""
    if not raw_tool_calls:
        return ""
    first_tool_call = raw_tool_calls[0]
    function_payload = first_tool_call.get("function", {})
    if not isinstance(function_payload, dict):
        return ""
    return str(function_payload.get("name", "")).strip()


def preview_text(text: str, *, max_len: int = 200) -> str:
    """生成文本预览，避免日志事件过大。"""
    normalized = str(text or "").strip()
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len]}..."


def latest_tool_error(tool_events: list[dict[str, Any]]) -> str:
    """提取最近一次工具错误信息。"""
    for event in reversed(tool_events):
        if str(event.get("event", "")).strip() != "tool_result":
            continue
        payload = event.get("result")
        if not isinstance(payload, dict):
            continue
        error_text = str(payload.get("error", "")).strip()
        if error_text:
            return error_text
    return ""


def has_tool_activity(tool_events: list[dict[str, Any]]) -> bool:
    """判断本轮是否存在真实工具活动（tool_call / tool_result）。"""
    for event in tool_events:
        event_name = str(event.get("event", "")).strip()
        if event_name in {"tool_call", "tool_result"}:
            return True
    return False


def build_empty_final_text(tool_events: list[dict[str, Any]]) -> str:
    """构建模型空文本输出时的兜底回复。"""
    latest_error = latest_tool_error(tool_events)
    if latest_error:
        return f"模型未返回有效文本结果。最近一次工具执行失败：{latest_error}"
    if has_tool_activity(tool_events):
        return "模型未返回有效文本结果。工具已执行，但未产出最终答复，请重试。"
    return "模型未返回有效文本结果，且未发起工具调用，请重试或切换更稳定的工具模型。"


class OpenAIGateway(LLMGatewayPort):
    """OpenAI 接口实现。"""

    def __init__(self, tool_runner: BuiltinToolRunner) -> None:
        """初始化工具执行器依赖。"""
        self.tool_runner = tool_runner

    async def run_with_tools(
        self,
        user_id: str,
        employee_id: str,
        messages: list[dict[str, Any]],
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
        refresh_system_message: SystemMessageRefresher | None = None,
    ) -> LLMRunResult:
        """执行一次可带工具循环的 LLM 调用。"""
        # working_messages 会在每轮中追加 assistant/tool 消息，
        # 作为下一轮模型输入，实现“模型 -> 工具 -> 模型”的闭环。
        working_messages = [dict(m) for m in messages]
        tool_events: list[dict[str, Any]] = []
        latest_usage: dict[str, Any] | None = None

        normalized_base_url = normalize_openai_base_url(llm_config.base_url)
        endpoint_url = build_chat_completions_endpoint(normalized_base_url)
        client = AsyncOpenAI(
            api_key=llm_config.api_key,
            base_url=normalized_base_url,
            timeout=120.0,
        )
        try:
            for round_index in range(max_tool_rounds):
                # 记录请求快照，便于审计和排障。
                system_prompt = ""
                for message in working_messages:
                    if str(message.get("role", "")).strip() == "system":
                        system_prompt = str(message.get("content", "") or "")
                        break
                request_body = {
                    "model": llm_config.model,
                    "messages": working_messages,
                    "tools": TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "temperature": DEFAULT_TEMPERATURE,
                    "max_completion_tokens": DEFAULT_MAX_COMPLETION_TOKENS,
                    "parallel_tool_calls": DEFAULT_PARALLEL_TOOL_CALLS,
                    "reasoning_effort": DEFAULT_REASONING_EFFORT,
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
                    "prompt_record": {
                        "system_prompt": system_prompt,
                        "message_count": len(working_messages),
                    },
                    "request_body": request_snapshot,
                }
                await record_event(llm_request_event, tool_events=tool_events, callback=on_event)

                request_started_at = perf_counter()
                try:
                    # 只使用官方 typed 参数构建请求，减少 SDK 升级时的类型歧义。
                    response = await client.chat.completions.create(
                        model=llm_config.model,
                        messages=build_typed_messages(working_messages),
                        tools=build_typed_tools(),
                        tool_choice="auto",
                        temperature=DEFAULT_TEMPERATURE,
                        max_completion_tokens=DEFAULT_MAX_COMPLETION_TOKENS,
                        parallel_tool_calls=DEFAULT_PARALLEL_TOOL_CALLS,
                        reasoning_effort=DEFAULT_REASONING_EFFORT,
                    )
                except APIStatusError as exc:
                    await record_event(
                        {
                            "event": "meta",
                            "type": "llm_error",
                            "user_id": user_id,
                            "round": round_index + 1,
                            "error": f"HTTP {exc.status_code}: {exc}",
                        },
                        tool_events=tool_events,
                        callback=on_event,
                    )
                    raise RuntimeError(f"模型接口调用失败（HTTP {exc.status_code}）：{exc}") from exc
                except APITimeoutError as exc:
                    await record_event(
                        {
                            "event": "meta",
                            "type": "llm_error",
                            "user_id": user_id,
                            "round": round_index + 1,
                            "error": f"timeout: {exc}",
                        },
                        tool_events=tool_events,
                        callback=on_event,
                    )
                    raise RuntimeError(f"模型接口连接超时：{exc}") from exc
                except APIConnectionError as exc:
                    await record_event(
                        {
                            "event": "meta",
                            "type": "llm_error",
                            "user_id": user_id,
                            "round": round_index + 1,
                            "error": f"connection: {exc}",
                        },
                        tool_events=tool_events,
                        callback=on_event,
                    )
                    raise RuntimeError(f"模型接口连接失败：{exc}") from exc
                except Exception as exc:  # noqa: BLE001
                    await record_event(
                        {
                            "event": "meta",
                            "type": "llm_error",
                            "user_id": user_id,
                            "round": round_index + 1,
                            "error": str(exc),
                        },
                        tool_events=tool_events,
                        callback=on_event,
                    )
                    raise RuntimeError(f"模型接口调用异常：{exc}") from exc

                latest_usage = extract_usage(response)
                message = extract_message(response)
                raw_content = getattr(message, "content", None)
                if raw_content is None and isinstance(message, dict):
                    raw_content = message.get("content")
                content = coerce_content(raw_content)
                raw_tool_calls = extract_raw_tool_calls(message)
                tool_calls_from_markup = False
                if not raw_tool_calls:
                    raw_tool_calls = extract_kimi_markup_tool_calls(content)
                    if raw_tool_calls:
                        tool_calls_from_markup = True
                        # Kimi 在部分网关会将 tool_calls 以特殊 token 文本返回，这里去除标记避免污染最终答复。
                        content = strip_kimi_tool_markup(content)
                normalized_tool_calls = [
                    normalize_tool_call(call, fallback_id=f"tool_call_{round_index}_{idx}")
                    for idx, call in enumerate(raw_tool_calls)
                ]
                llm_response_event: dict[str, Any] = {
                    "event": "meta",
                    "type": "llm_response",
                    "user_id": user_id,
                    "round": round_index + 1,
                    "latency_ms": int((perf_counter() - request_started_at) * 1000),
                    "finish_reason": extract_finish_reason(response),
                    "has_tool_calls": bool(normalized_tool_calls),
                    "tool_call_count": len(normalized_tool_calls),
                    "content_length": len(content.strip()),
                }
                if latest_usage is not None:
                    llm_response_event["usage"] = latest_usage
                tool_name = extract_tool_name(normalized_tool_calls)
                if tool_name:
                    llm_response_event["function_name"] = tool_name
                if tool_calls_from_markup:
                    llm_response_event["tool_calls_from_markup"] = True
                content_preview = preview_text(content, max_len=240)
                if content_preview:
                    llm_response_event["content_preview"] = content_preview
                await record_event(llm_response_event, tool_events=tool_events, callback=on_event)

                if normalized_tool_calls:
                    # 本轮返回了工具调用：先追加 assistant+tool_calls，再交给工具循环处理。
                    assistant_tool_content = content.strip()
                    working_messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_tool_content or None,
                            "tool_calls": normalized_tool_calls,
                        }
                    )
                    await process_tool_calls(
                        round_index=round_index,
                        normalized_tool_calls=normalized_tool_calls,
                        assistant_tool_content=assistant_tool_content,
                        user_id=user_id,
                        employee_id=employee_id,
                        tool_runner=self.tool_runner,
                        llm_config=llm_config,
                        working_messages=working_messages,
                        on_event=on_event,
                        tool_events=tool_events,
                        refresh_system_message=refresh_system_message,
                    )
                    continue

                # 没有工具调用则本轮即最终答案，直接返回。
                final_text = content.strip()
                if not final_text:
                    final_text = build_empty_final_text(tool_events)
                working_messages.append({"role": "assistant", "content": final_text})
                return LLMRunResult(
                    assistant_text=final_text,
                    tool_events=tool_events,
                    usage=latest_usage,
                    working_messages=working_messages,
                    reached_tool_limit=False,
                )
        finally:
            await client.close()

        # 超过工具轮次上限仍未收敛时，返回可读兜底文案并标记 reached_tool_limit。
        fallback_text = (
            f"工具调用超过最大轮次限制（{max_tool_rounds}），已中止本次调用。"
            "请收敛工具调用步骤后重试。"
        )
        return LLMRunResult(
            assistant_text=fallback_text,
            tool_events=tool_events,
            usage=latest_usage,
            working_messages=working_messages,
            reached_tool_limit=True,
        )
