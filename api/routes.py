"""HTTP 路由定义与请求处理编排。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from domain.models import LLMConfig
from api.dependencies import AppContainer
from api.requests import (
    ChatStreamRequest,
    FlushRequest,
    MemoryFileUpdateRequest,
    SessionCreateRequest,
    SettingsUpdateRequest,
)
from api.sse import SSEEnvelopeBuilder
from common.errors import AppError, NotFoundError, ValidationError
from common.ids import normalize_user_id
from common.response import error_response, success_response


def _normalize_session_id(session_id: str | None, *, default: str = "default") -> str:
    """标准化会话 ID，空值时回退到默认会话。"""
    normalized = str(session_id or "").strip()
    if not normalized:
        return default
    return normalized


def _new_request_id() -> str:
    """生成请求级追踪 ID。"""
    return uuid4().hex


def _raise_http(error: AppError, request_id: str) -> HTTPException:
    """将应用异常转换为 HTTPException，并保持统一响应结构。"""
    return HTTPException(status_code=error.status_code, detail=error_response(request_id=request_id, error=error))


def _memory_status_to_dict(status: Any) -> dict[str, Any]:
    """将多种状态对象统一转换为 ``dict``，便于序列化返回。"""
    if hasattr(status, "__dict__"):
        return dict(status.__dict__)
    if isinstance(status, dict):
        return status
    if hasattr(status, "model_dump"):
        dumped = status.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return asdict(status)


def create_router(container: AppContainer) -> APIRouter:
    """基于容器依赖创建 API 路由。"""
    router = APIRouter()

    @router.get("/sessions")
    async def list_sessions(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """查询用户下的会话列表。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            sessions = await container.session_service.list_sessions(normalized_user_id, limit=300)
            data = {"sessions": [asdict(item) for item in sessions]}
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.post("/sessions")
    async def create_session(request: SessionCreateRequest) -> JSONResponse:
        """创建新会话。"""
        request_id = _new_request_id()
        try:
            user_id = normalize_user_id(request.user_id)
            await container.memory_file_service.ensure_user_files(user_id)
            entry = await container.session_service.create_session(user_id, request.session_id)
            return JSONResponse(success_response(request_id=request_id, data={"created": True, "session": asdict(entry)}))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.get("/session-messages")
    async def get_session_messages(
        user_id: str = Query(..., min_length=1),
        session_id: str = Query(..., min_length=1),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        """查询指定会话的历史消息。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            normalized_session_id = _normalize_session_id(session_id)
            messages = await container.session_service.list_session_messages(
                normalized_user_id,
                normalized_session_id,
                limit=limit,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "user_id": normalized_user_id,
                        "session_id": normalized_session_id,
                        "messages": [asdict(item) for item in messages],
                    },
                )
            )
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.get("/settings")
    async def get_settings(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """读取用户模型配置。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            settings = await container.settings_service.get_settings(normalized_user_id)
            data = {
                "model": settings.model,
                "api_key": settings.api_key,
                "base_url": settings.base_url,
                "max_tool_rounds": settings.max_tool_rounds,
                "total_token_limit": settings.total_token_limit,
            }
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.put("/settings")
    async def update_settings(body: SettingsUpdateRequest) -> JSONResponse:
        """更新用户模型配置。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(body.user_id)
            latest = await container.settings_service.update_settings(
                user_id=normalized_user_id,
                model=body.model,
                api_key=body.api_key,
                base_url=body.base_url,
                max_tool_rounds=body.max_tool_rounds,
                total_token_limit=body.total_token_limit,
            )
            data = {
                "model": latest.model,
                "api_key": latest.api_key,
                "base_url": latest.base_url,
                "max_tool_rounds": latest.max_tool_rounds,
                "total_token_limit": latest.total_token_limit,
            }
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.post("/chat/stream")
    async def chat_stream(request: ChatStreamRequest, background_tasks: BackgroundTasks) -> StreamingResponse:
        """以 SSE 方式流式返回聊天结果与工具调用事件。"""
        request_id = _new_request_id()
        user_id = normalize_user_id(request.user_id)
        session_id = _normalize_session_id(request.session_id)

        # 对话前确保用户记忆文件可用，并读取当前用户模型配置。
        await container.memory_file_service.ensure_user_files(user_id)
        settings = await container.settings_service.get_settings(user_id)
        llm_config = LLMConfig(model=settings.model, api_key=settings.api_key, base_url=settings.base_url)
        max_tool_rounds = request.max_tool_rounds or settings.max_tool_rounds

        async def event_stream() -> AsyncIterator[str]:
            """将用例产出的内部事件转发为 SSE 事件流。"""
            builder = SSEEnvelopeBuilder(request_id=request_id, session_id=session_id)
            yield builder.frame(
                "meta",
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "model": llm_config.model,
                    "max_tool_rounds": max_tool_rounds,
                },
            )

            event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def forward_agent_event(event: dict[str, Any]) -> None:
                # 用例可能在任意时刻产出工具事件，这里统一进队列后再按顺序输出。
                await event_queue.put(dict(event))

            process_task = asyncio.create_task(
                container.chat_stream_use_case.execute(
                    user_id=user_id,
                    session_id=session_id,
                    message=request.message,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                    on_event=forward_agent_event,
                )
            )

            async def drain_queue() -> list[dict[str, Any]]:
                """在任务结束后把尚未消费的事件一次性取出。"""
                pending: list[dict[str, Any]] = []
                while not event_queue.empty():
                    pending.append(event_queue.get_nowait())
                return pending

            async def cancel_task_silently(task: asyncio.Task[Any]) -> None:
                """取消后台任务并吞掉取消阶段异常，防止污染 SSE 连接。"""
                if task.done():
                    return
                task.cancel()
                try:
                    await task
                except Exception:  # noqa: BLE001
                    pass

            def map_event(raw_event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                """将内部事件映射为前端约定的 SSE 事件类型。"""
                event_name = str(raw_event.get("event") or "meta")
                if event_name in {"tool_call", "tool_result"}:
                    return event_name, raw_event
                if event_name == "meta":
                    return "meta", raw_event
                return "meta", raw_event

            try:
                # 循环消费事件队列，直到主处理任务结束。
                while not process_task.done():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    event_type, payload = map_event(event)
                    yield builder.frame(event_type, payload)

                result = await process_task

                # 任务结束后再冲刷一次队列，避免尾部事件丢失。
                for event in await drain_queue():
                    event_type, payload = map_event(event)
                    yield builder.frame(event_type, payload)

                yield builder.frame(
                    "assistant_final",
                    {"content": result.assistant_text, "usage": result.usage or {}},
                )

                if result.flush_scheduled:
                    # 自动刷盘采用后台任务，避免阻塞本次流式请求。
                    background_tasks.add_task(
                        container.flush_use_case.flush,
                        user_id=user_id,
                        session_id=session_id,
                        llm_config=llm_config,
                        max_tool_rounds=max_tool_rounds,
                    )
                    yield builder.frame("meta", {"flush_scheduled": True, "reason": "触发token阈值"})

                yield builder.frame("memory_status", _memory_status_to_dict(result.status))
                yield builder.frame("done", {"ok": True})
            except Exception as exc:  # noqa: BLE001
                # 异常时也尽量把已产生事件发送完，再返回错误终止标记。
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

    @router.get("/memory/status")
    async def memory_status(
        user_id: str = Query(..., min_length=1),
        session_id: str = Query(default="default", min_length=1),
        model: str | None = Query(default=None),
    ) -> JSONResponse:
        """获取会话当前记忆状态。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            normalized_session_id = _normalize_session_id(session_id)
            await container.memory_file_service.ensure_user_files(normalized_user_id)
            if model:
                model_name = str(model).strip() or "agent-advoo"
            else:
                model_name = (await container.settings_service.get_settings(normalized_user_id)).model
            status = await container.memory_status_use_case.execute(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                model=model_name,
            )
            return JSONResponse(success_response(request_id=request_id, data=_memory_status_to_dict(status)))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.get("/memory/files")
    async def memory_files(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """列出用户记忆文件。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            await container.memory_file_service.ensure_user_files(normalized_user_id)
            files = await container.memory_file_service.list_files(normalized_user_id)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"files": [asdict(item) for item in files]},
                )
            )
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.post("/memory/reset")
    async def reset_memory_files(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """重置用户记忆文件为默认内容。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            restored_files, files = await container.memory_file_service.reset_files(normalized_user_id)
            data = {
                "ok": True,
                "restored_files": restored_files,
                "files": [asdict(item) for item in files],
            }
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.put("/memory/files/{file_name}")
    async def update_memory_file(
        file_name: str,
        body: MemoryFileUpdateRequest,
        user_id: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """更新单个记忆文件内容。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            await container.memory_file_service.ensure_user_files(normalized_user_id)
            latest = await container.memory_file_service.update_file(
                user_id=normalized_user_id,
                file_name=file_name,
                content=body.content,
                mode=body.mode,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"ok": True, "file_name": file_name, "content": latest},
                )
            )
        except NotFoundError as exc:
            raise _raise_http(exc, request_id) from exc
        except ValidationError as exc:
            raise _raise_http(exc, request_id) from exc
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    @router.post("/memory/flush")
    async def memory_flush(request: FlushRequest, background_tasks: BackgroundTasks) -> JSONResponse:
        """手动触发会话记忆刷盘。"""
        request_id = _new_request_id()
        try:
            normalized_user_id = normalize_user_id(request.user_id)
            normalized_session_id = _normalize_session_id(request.session_id)
            await container.memory_file_service.ensure_user_files(normalized_user_id)

            settings = await container.settings_service.get_settings(normalized_user_id)
            llm_config = LLMConfig(model=settings.model, api_key=settings.api_key, base_url=settings.base_url)
            max_tool_rounds = request.max_tool_rounds or settings.max_tool_rounds

            accepted = await container.flush_use_case.try_start_manual_flush(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
            )
            if accepted:
                background_tasks.add_task(
                    container.flush_use_case.flush,
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    llm_config=llm_config,
                    max_tool_rounds=max_tool_rounds,
                )
            status = await container.memory_status_use_case.execute(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                model=llm_config.model,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "accepted": accepted,
                        "user_id": normalized_user_id,
                        "session_id": normalized_session_id,
                        "is_flushing": status.is_flushing,
                    },
                )
            )
        except AppError as exc:
            raise _raise_http(exc, request_id) from exc

    return router
