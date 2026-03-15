"""工具调用协议校验与消息裁剪修复逻辑。"""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(raw_text: str) -> dict[str, Any] | None:
    """解析输入并返回结构化结果。"""
    try:
        parsed = json.loads(raw_text)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def to_json_string(value: Any, *, default: str = "{}") -> str:
    """执行 to_json_string 相关逻辑。"""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def to_tool_content(value: Any) -> str:
    """执行 to_tool_content 相关逻辑。"""
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


def normalize_prompt_role(raw_role: Any) -> str:
    """规范化输入值。"""
    role = str(raw_role).strip()
    if role in {"system", "user", "assistant", "tool", "function"}:
        return role
    return "assistant"


def normalize_message_kind(row: dict[str, Any]) -> str:
    """规范化消息类型。"""
    candidate = str(row.get("message_kind", "")).strip().lower()
    if candidate in {"chat", "tool_call", "tool_result"}:
        return candidate
    return "chat"


def sanitize_active_rows_for_tool_protocol(
    rows: list[dict[str, Any]],
    *,
    previous_role: str | None = None,
) -> list[dict[str, Any]]:
    """
    清洗裁剪后的 active rows，避免出现工具协议顺序错误。"""
    sanitized: list[dict[str, Any]] = []
    known_tool_calls: set[str] = set()
    last_role = previous_role if previous_role in {"user", "assistant", "tool", "function"} else None

    for row in rows:
        if normalize_message_kind(row) not in {"tool_call", "tool_result"}:
            sanitized.append(row)
            normalized_role = normalize_prompt_role(row.get("role", "assistant"))
            last_role = "assistant" if normalized_role in {"tool", "function"} else normalized_role
            continue

        payload = parse_json_object(str(row.get("content", "")))
        if payload is None:
            continue

        event_name = str(payload.get("event", "")).strip()
        row_id = row.get("id")
        fallback_id = f"tool_call_{row_id}" if row_id is not None else "tool_call_unknown"
        tool_call_id = str(payload.get("tool_call_id", "")).strip() or fallback_id

        if event_name == "tool_call":
            if last_role not in {"user", "tool"}:
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


def build_message_from_tool_event_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """构建目标结构。"""
    raw_content = str(row.get("content", ""))
    payload = parse_json_object(raw_content)
    if payload is None:
        return None

    event_name = str(payload.get("event", "")).strip()
    row_id = row.get("id")
    fallback_tool_call_id = f"tool_call_{row_id}" if row_id is not None else "tool_call_unknown"

    if event_name == "tool_call":
        tool_call_id = str(payload.get("tool_call_id", "")).strip() or fallback_tool_call_id
        tool_name = str(payload.get("tool_name", "")).strip() or f"unknown_tool_{tool_call_id}"
        arguments = to_json_string(payload.get("arguments", {}), default="{}")

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
        result_content = to_tool_content(payload.get("result", ""))
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result_content,
        }

    return None


def is_tool_persistable_event(event: dict[str, Any]) -> bool:
    """判断事件是否需要持久化到消息表（含 debug 用 meta 事件）。"""
    event_name = str(event.get("event", "")).strip()
    if event_name in {"tool_call", "tool_result"}:
        return True
    if event_name != "meta":
        return False
    meta_type = str(event.get("type", "")).strip()
    return meta_type in {"llm_request", "llm_response", "llm_error", "state_refresh"}
