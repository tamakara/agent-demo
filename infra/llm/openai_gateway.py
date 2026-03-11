"""OpenAI 网关适配与多轮工具调用驱动。"""

from __future__ import annotations

import json
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
    extract_message,
    extract_usage,
    normalize_openai_base_url,
    normalize_tool_call,
)
from infra.llm.tool_loop import process_tool_calls
from infra.tools.builtin_tools import BuiltinToolRunner
from infra.tools.tool_registry import TOOL_SCHEMAS


class OpenAIGateway(LLMGatewayPort):
    """OpenAI 兼容接口实现。"""

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
                await record_event(llm_request_event, tool_events=tool_events, callback=on_event)

                try:
                    # 只使用官方 typed 参数构建请求，减少 SDK 升级时的类型歧义。
                    response = await client.chat.completions.create(
                        model=llm_config.model,
                        messages=build_typed_messages(working_messages),
                        tools=build_typed_tools(),
                        tool_choice="auto",
                    )
                except APIStatusError as exc:
                    raise RuntimeError(f"模型接口调用失败（HTTP {exc.status_code}）：{exc}") from exc
                except APITimeoutError as exc:
                    raise RuntimeError(f"模型接口连接超时：{exc}") from exc
                except APIConnectionError as exc:
                    raise RuntimeError(f"模型接口连接失败：{exc}") from exc
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"模型接口调用异常：{exc}") from exc

                latest_usage = extract_usage(response)
                message = extract_message(response)
                content = coerce_content(getattr(message, "content", None))
                raw_tool_calls = getattr(message, "tool_calls", None) or []
                normalized_tool_calls = [
                    normalize_tool_call(call, fallback_id=f"tool_call_{round_index}_{idx}")
                    for idx, call in enumerate(raw_tool_calls)
                ]

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
                        working_messages=working_messages,
                        on_event=on_event,
                        tool_events=tool_events,
                        refresh_system_message=refresh_system_message,
                    )
                    continue

                # 没有工具调用则本轮即最终答案，直接返回。
                final_text = content.strip()
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
