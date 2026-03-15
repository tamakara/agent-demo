"""聊天与记忆模块路由。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import JSONResponse, StreamingResponse

from api.dependencies import AppContainer
from api.requests import ChatStreamRequest, FlushRequest
from api.routes_shared import FIXED_MAX_TOOL_ROUNDS, memory_status_to_dict, new_request_id, normalize_user_path, raise_http
from api.routes_shared import resolve_employee
from api.sse import SSEEnvelopeBuilder
from common.errors import AppError
from common.response import success_response
from domain.models import LLMConfig


def create_chat_router(container: AppContainer) -> APIRouter:
    """创建聊天与记忆相关路由。"""
    router = APIRouter(tags=["chat"])

    @router.post("/chat/stream")
    async def chat_stream(
        request: ChatStreamRequest,
        background_tasks: BackgroundTasks,
    ) -> StreamingResponse:
        """以 SSE 方式流式返回聊天结果与工具调用事件。"""
        request_id = new_request_id()
        normalized_user_id = normalize_user_path(request.user_id)
        normalized_employee_id, session_id = await resolve_employee(
            container,
            user_id=normalized_user_id,
            employee_id=request.employee_id,
            auto_create_default=True,
        )

        await container.memory_file_service.ensure_employee_files(normalized_user_id, normalized_employee_id)
        settings = await container.settings_service.get_settings(normalized_user_id)
        llm_config = LLMConfig(model=settings.model, api_key=settings.api_key, base_url=settings.base_url)
        max_tool_rounds = FIXED_MAX_TOOL_ROUNDS

        async def event_stream() -> AsyncIterator[str]:
            builder = SSEEnvelopeBuilder(
                request_id=request_id,
                employee_id=normalized_employee_id,
                session_id=session_id,
            )
            yield builder.frame(
                "meta",
                {
                    "user_id": normalized_user_id,
                    "employee_id": normalized_employee_id,
                    "session_id": session_id,
                    "model": llm_config.model,
                    "max_tool_rounds": max_tool_rounds,
                },
            )

            event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def forward_agent_event(event: dict[str, Any]) -> None:
                await event_queue.put(dict(event))

            process_task = asyncio.create_task(
                container.chat_stream_use_case.execute(
                    user_id=normalized_user_id,
                    employee_id=normalized_employee_id,
                    session_id=session_id,
                    message=request.message,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                    on_event=forward_agent_event,
                )
            )

            async def drain_queue() -> list[dict[str, Any]]:
                pending: list[dict[str, Any]] = []
                while not event_queue.empty():
                    pending.append(event_queue.get_nowait())
                return pending

            async def cancel_task_silently(task: asyncio.Task[Any]) -> None:
                if task.done():
                    return
                task.cancel()
                try:
                    await task
                except Exception:  # noqa: BLE001
                    pass

            def map_event(raw_event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                event_name = str(raw_event.get("event") or "meta")
                if event_name in {"tool_call", "tool_result"}:
                    return event_name, raw_event
                if event_name == "meta":
                    return "meta", raw_event
                return "meta", raw_event

            try:
                while not process_task.done():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    event_type, payload = map_event(event)
                    yield builder.frame(event_type, payload)

                result = await process_task

                for event in await drain_queue():
                    event_type, payload = map_event(event)
                    yield builder.frame(event_type, payload)

                yield builder.frame(
                    "assistant_final",
                    {"content": result.assistant_text, "usage": result.usage or {}},
                )

                if result.flush_scheduled:
                    background_tasks.add_task(
                        container.flush_use_case.flush,
                        user_id=normalized_user_id,
                        employee_id=normalized_employee_id,
                        session_id=session_id,
                        llm_config=llm_config,
                        max_tool_rounds=max_tool_rounds,
                    )
                    yield builder.frame("meta", {"flush_scheduled": True, "reason": "触发token阈值"})

                yield builder.frame("memory_status", memory_status_to_dict(result.status))
                yield builder.frame("done", {"ok": True})
            except Exception as exc:  # noqa: BLE001
                for event in await drain_queue():
                    event_type, payload = map_event(event)
                    yield builder.frame(event_type, payload)
                await cancel_task_silently(process_task)
                yield builder.frame("error", {"message": f"请求处理失败：{exc}"})
                yield builder.frame("done", {"ok": False})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            background=background_tasks,
        )

    @router.get("/chat/memory/status")
    async def memory_status(
        user_id: str = Query(..., min_length=1),
        employee_id: str = Query(default="1", min_length=1),
        model: str | None = Query(default=None),
    ) -> JSONResponse:
        """获取数字员工当前记忆状态。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            normalized_employee_id, session_id = await resolve_employee(
                container,
                user_id=normalized_user_id,
                employee_id=employee_id,
                auto_create_default=True,
            )
            await container.memory_file_service.ensure_employee_files(normalized_user_id, normalized_employee_id)
            if model:
                model_name = str(model).strip() or "agent-advoo"
            else:
                model_name = (await container.settings_service.get_settings(normalized_user_id)).model
            status = await container.memory_status_use_case.execute(
                user_id=normalized_user_id,
                employee_id=normalized_employee_id,
                session_id=session_id,
                model=model_name,
            )
            return JSONResponse(success_response(request_id=request_id, data=memory_status_to_dict(status)))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/chat/memory/flush")
    async def memory_flush(
        request: FlushRequest,
        background_tasks: BackgroundTasks,
    ) -> JSONResponse:
        """手动触发数字员工记忆刷盘。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(request.user_id)
            normalized_employee_id, session_id = await resolve_employee(
                container,
                user_id=normalized_user_id,
                employee_id=request.employee_id,
                auto_create_default=True,
            )
            await container.memory_file_service.ensure_employee_files(normalized_user_id, normalized_employee_id)

            settings = await container.settings_service.get_settings(normalized_user_id)
            llm_config = LLMConfig(model=settings.model, api_key=settings.api_key, base_url=settings.base_url)
            max_tool_rounds = FIXED_MAX_TOOL_ROUNDS

            accepted = await container.flush_use_case.try_start_manual_flush(
                user_id=normalized_user_id,
                session_id=session_id,
            )
            if accepted:
                background_tasks.add_task(
                    container.flush_use_case.flush,
                    user_id=normalized_user_id,
                    employee_id=normalized_employee_id,
                    session_id=session_id,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                )
            status = await container.memory_status_use_case.execute(
                user_id=normalized_user_id,
                employee_id=normalized_employee_id,
                session_id=session_id,
                model=llm_config.model,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "accepted": accepted,
                        "user_id": normalized_user_id,
                        "employee_id": normalized_employee_id,
                        "session_id": session_id,
                        "is_flushing": status.is_flushing,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    return router
