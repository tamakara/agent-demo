"""LLM 事件发布与事件记录辅助函数。"""

from __future__ import annotations

from typing import Any

from app.ports.repositories import EventCallback


async def emit(event: dict[str, Any], callback: EventCallback | None) -> None:
    """发布事件。"""
    if callback is None:
        return
    maybe_coro = callback(event)
    if maybe_coro is not None:
        await maybe_coro


async def record_event(
    event: dict[str, Any],
    *,
    tool_events: list[dict[str, Any]],
    callback: EventCallback | None,
) -> None:
    """记录事件信息。"""
    tool_events.append(event)
    await emit(event, callback)


