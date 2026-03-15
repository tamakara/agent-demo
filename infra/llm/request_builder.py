"""OpenAI 请求参数规范化与消息构建。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, cast

from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam

from infra.tools.tool_registry import TOOL_SCHEMAS


OPENAI_DEFAULT_BASE_URL = "http://model-gateway.test.api.dotai.internal/v1"
OPENAI_SUFFIX_CHAT_COMPLETIONS = "/chat/completions"
FALLBACK_TOOL_NAME_PREFIX = "unknown_tool"


def normalize_openai_base_url(base_url: str | None) -> str:
    """规范化 OpenAI 基础地址，去除尾部 ``/chat/completions``。"""
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


def build_chat_completions_endpoint(base_url: str) -> str:
    """基于基础地址构建 chat completions 完整端点。"""
    normalized = base_url.rstrip("/")
    return f"{normalized}/chat/completions"


def normalize_tool_name(name: Any, fallback_suffix: str) -> str:
    """规范化工具名，空值时生成兜底名称。"""
    candidate = str(name or "").strip()
    if candidate:
        lowered = candidate.lower()
        for prefix in ("functions.", "function.", "tools.", "tool."):
            if lowered.startswith(prefix):
                candidate = candidate[len(prefix) :]
                break
    if candidate:
        return candidate
    return f"{FALLBACK_TOOL_NAME_PREFIX}_{fallback_suffix}"


def stringify_tool_arguments(raw_arguments: Any) -> str:
    """将工具参数序列化为 JSON 字符串。"""
    if isinstance(raw_arguments, str):
        return raw_arguments
    if raw_arguments is None:
        return "{}"
    if isinstance(raw_arguments, (dict, list)):
        return json.dumps(raw_arguments, ensure_ascii=False)
    return str(raw_arguments)


def normalize_tool_call(raw_tool_call: Any, fallback_id: str) -> dict[str, Any]:
    """将输入统一为标准 tool_call 字典。"""
    if hasattr(raw_tool_call, "model_dump"):
        raw_tool_call = raw_tool_call.model_dump()

    if isinstance(raw_tool_call, dict):
        function_data = raw_tool_call.get("function", {})
        if hasattr(function_data, "model_dump"):
            function_data = function_data.model_dump()
        if not isinstance(function_data, dict):
            function_data = {}
        normalized_id = str(raw_tool_call.get("id") or fallback_id)
        normalized_name = normalize_tool_name(
            function_data.get("name", raw_tool_call.get("name", "")),
            fallback_suffix=normalized_id,
        )
        return {
            "id": normalized_id,
            "type": "function",
            "function": {
                "name": normalized_name,
                "arguments": stringify_tool_arguments(
                    function_data.get("arguments", raw_tool_call.get("arguments", "{}"))
                ),
            },
        }

    function_data = getattr(raw_tool_call, "function", None)
    name = ""
    arguments: Any = "{}"
    if function_data is not None:
        name = str(getattr(function_data, "name", ""))
        arguments = getattr(function_data, "arguments", "{}")
    if not name:
        name = str(getattr(raw_tool_call, "name", ""))
        arguments = getattr(raw_tool_call, "arguments", arguments)
    normalized_id = str(getattr(raw_tool_call, "id", fallback_id))
    normalized_name = normalize_tool_name(name, fallback_suffix=normalized_id)
    return {
        "id": normalized_id,
        "type": "function",
        "function": {
            "name": normalized_name,
            "arguments": stringify_tool_arguments(arguments),
        },
    }


def coerce_content(content: Any) -> str:
    """将多形态 content 统一转换为文本。"""
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


def extract_usage(response: Any) -> dict[str, Any] | None:
    """从响应对象中提取 usage 信息。"""
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


def extract_message(response: Any) -> Any:
    """提取首个 choice 的 message 字段。"""
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM 返回结果缺少 choices 字段")
    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    if message is None and isinstance(first_choice, dict):
        message = first_choice.get("message")
    if message is None:
        raise ValueError("LLM 返回结果缺少 message 字段")
    return message


def extract_raw_tool_calls(message: Any) -> list[Any]:
    """从 message 提取标准 ``tool_calls``。"""
    raw_tool_calls = getattr(message, "tool_calls", None)
    if raw_tool_calls is None and isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls")
    if not raw_tool_calls:
        return []
    if isinstance(raw_tool_calls, list):
        return raw_tool_calls
    return [raw_tool_calls]


def serialize_tool_content(payload: Any) -> str:
    """将工具结果 payload 序列化为 ``tool`` 消息 content。"""
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


def build_typed_messages(messages: list[dict[str, Any]]) -> Iterable[ChatCompletionMessageParam]:
    """将动态消息列表转为 OpenAI SDK 所需类型。"""
    return cast(Iterable[ChatCompletionMessageParam], messages)


def build_typed_tools() -> Iterable[ChatCompletionToolUnionParam]:
    """将工具 schema 列表转为 OpenAI SDK 所需类型。"""
    return cast(Iterable[ChatCompletionToolUnionParam], TOOL_SCHEMAS)
