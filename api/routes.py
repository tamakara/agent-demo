"""资源化 REST 路由与 SSE 流式接口。

本模块的职责边界：
1. 解析/校验 HTTP 入参（路径参数、Query、Body）。
2. 调用 app 层服务完成业务处理。
3. 将业务异常统一映射为标准 HTTP 错误响应。
4. 对 SSE 结果进行事件封包与流式输出。

设计约束：
- API 层不承载业务决策。
- API 层不直接访问数据库或第三方 SDK。
"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Path as FastAPIPath, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from api.dependencies import AppContainer
from api.response import error_response, success_response
from api.schemas import ChatStreamBody, FileContentUpdateBody, SettingsUpdateBody
from api.sse import SSEEnvelopeBuilder
from app.errors import AppError, ValidationError
from app.id_codec import normalize_employee_id, normalize_user_id, session_id_from_employee_id
from app.services.settings_service import FIXED_MAX_TOOL_ROUNDS
from infra.memory.storage_layout import user_brand_library_dir


# 允许通过预览接口直接返回的图片后缀白名单。
PREVIEWABLE_IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp", ".gif", ".bmp", ".svg"}


def new_request_id() -> str:
    """生成请求追踪 ID。"""
    return uuid4().hex


def raise_http(error: AppError, request_id: str) -> HTTPException:
    """把应用层异常包装为 HTTPException，并保持统一错误结构。"""
    return HTTPException(status_code=error.status_code, detail=error_response(request_id=request_id, error=error))


def _ensure_session_binding(employee_id: str, session_id: str) -> None:
    """校验 session_id 与 employee_id 的绑定关系。

    当前系统约定：`session_id = employee-{employee_id}`。
    """
    expected = session_id_from_employee_id(employee_id)
    if session_id != expected:
        raise ValidationError(
            f"session_id 与 employee_id 不匹配：employee_id={employee_id}, expected={expected}, actual={session_id}"
        )


async def _resolve_employee(
    container: AppContainer,
    *,
    user_id: str,
    employee_id: str,
    auto_create_default: bool = True,
) -> tuple[str, str, str]:
    """统一解析并校验 user/employee，返回规范化身份信息。"""
    normalized_user_id = normalize_user_id(user_id)
    normalized_employee_id = normalize_employee_id(employee_id)
    employee = await container.employee_service.get_employee(
        normalized_user_id,
        normalized_employee_id,
        auto_create_default=auto_create_default,
    )
    return normalized_user_id, employee.employee_id, employee.session_id


def create_router(container: AppContainer) -> APIRouter:
    """创建并返回全部 API 路由。"""
    router = APIRouter()

    @router.get("/users/{user_id}/employees")
    async def list_employees(user_id: str = FastAPIPath(..., min_length=1)) -> JSONResponse:
        """列出用户下的全部数字员工。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            return JSONResponse(success_response(request_id=request_id, data={"employees": employees}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/users/{user_id}/employees")
    async def create_employee(user_id: str = FastAPIPath(..., min_length=1)) -> JSONResponse:
        """创建新数字员工，并初始化其记忆文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            entry = await container.employee_service.create_employee(normalized_user_id)
            await container.storage_service.ensure_employee_files(normalized_user_id, entry.employee_id)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"created": True, "employee": entry},
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.delete("/users/{user_id}/employees/{employee_id}")
    async def delete_employee(
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
    ) -> JSONResponse:
        """删除指定数字员工及其数据目录。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            normalized_employee_id = normalize_employee_id(employee_id)
            deleted = await container.employee_service.delete_employee(normalized_user_id, normalized_employee_id)
            await container.storage_service.delete_employee_data(normalized_user_id, normalized_employee_id)
            remaining = await container.employee_service.list_employees(normalized_user_id, limit=300)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"deleted": True, "employee": deleted, "employees": remaining},
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/users/{user_id}/employees/{employee_id}/reset")
    async def reset_employee(
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
    ) -> JSONResponse:
        """重置指定员工：删除后按同编号重建。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            normalized_employee_id = normalize_employee_id(employee_id)
            recreated = await container.employee_service.reset_employee(normalized_user_id, normalized_employee_id)
            await container.storage_service.delete_employee_data(normalized_user_id, normalized_employee_id)
            await container.storage_service.ensure_employee_files(normalized_user_id, normalized_employee_id)
            files = await container.storage_service.list_employee_files(normalized_user_id, normalized_employee_id)
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "ok": True,
                        "employee": recreated,
                        "employees": employees,
                        "files": files,
                        "tree": container.storage_service.list_data_paths(normalized_user_id),
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/users/{user_id}/employees/{employee_id}/messages")
    async def list_employee_messages(
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        """查询指定员工会话消息。"""
        request_id = new_request_id()
        try:
            normalized_user_id, normalized_employee_id, session_id = await _resolve_employee(
                container,
                user_id=user_id,
                employee_id=employee_id,
                auto_create_default=True,
            )
            messages = await container.employee_service.list_employee_messages(
                normalized_user_id,
                normalized_employee_id,
                limit=limit,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "user_id": normalized_user_id,
                        "employee_id": normalized_employee_id,
                        "session_id": session_id,
                        "messages": messages,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/users/{user_id}/settings")
    async def get_settings(user_id: str = FastAPIPath(..., min_length=1)) -> JSONResponse:
        """读取用户全局模型设置。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            settings = await container.settings_service.get_settings(normalized_user_id)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "model": settings.model,
                        "api_key": settings.api_key,
                        "base_url": settings.base_url,
                        "max_tool_rounds": FIXED_MAX_TOOL_ROUNDS,
                        "total_token_limit": settings.total_token_limit,
                        "tokenizer_model": settings.tokenizer_model,
                        "memory_capacity_ratio": settings.memory_capacity_ratio,
                        "notebook_capacity_ratio": settings.notebook_capacity_ratio,
                        "dialogue_summary_ratio": settings.dialogue_summary_ratio,
                        "retention_ratio": settings.retention_ratio,
                        "deep_thinking_enabled": settings.deep_thinking_enabled,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.put("/users/{user_id}/settings")
    async def update_settings(
        body: SettingsUpdateBody,
        user_id: str = FastAPIPath(..., min_length=1),
    ) -> JSONResponse:
        """更新用户全局模型设置。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            latest = await container.settings_service.update_settings(
                user_id=normalized_user_id,
                model=body.model,
                api_key=body.api_key,
                base_url=body.base_url,
                total_token_limit=body.total_token_limit,
                tokenizer_model=body.tokenizer_model,
                memory_capacity_ratio=body.memory_capacity_ratio,
                notebook_capacity_ratio=body.notebook_capacity_ratio,
                dialogue_summary_ratio=body.dialogue_summary_ratio,
                retention_ratio=body.retention_ratio,
                deep_thinking_enabled=body.deep_thinking_enabled,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "model": latest.model,
                        "api_key": latest.api_key,
                        "base_url": latest.base_url,
                        "max_tool_rounds": FIXED_MAX_TOOL_ROUNDS,
                        "total_token_limit": latest.total_token_limit,
                        "tokenizer_model": latest.tokenizer_model,
                        "memory_capacity_ratio": latest.memory_capacity_ratio,
                        "notebook_capacity_ratio": latest.notebook_capacity_ratio,
                        "dialogue_summary_ratio": latest.dialogue_summary_ratio,
                        "retention_ratio": latest.retention_ratio,
                        "deep_thinking_enabled": latest.deep_thinking_enabled,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/users/{user_id}/files/tree")
    async def list_user_files_tree(user_id: str = FastAPIPath(..., min_length=1)) -> JSONResponse:
        """返回用户目录树与员工记忆文件视图。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            for item in employees:
                await container.storage_service.ensure_employee_files(normalized_user_id, item.employee_id)

            files_payload: list[dict[str, Any]] = []
            for item in employees:
                files = await container.storage_service.list_employee_files(normalized_user_id, item.employee_id)
                for file_item in files:
                    relative = str(file_item.relative_path or "").lstrip("/")
                    # 对前端统一暴露 employee 视图路径，避免泄露存储层内部相对目录细节。
                    files_payload.append(
                        {
                            "file_name": file_item.file_name,
                            "relative_path": (
                                f"employee/{item.employee_id}/{relative}"
                                if relative
                                else f"employee/{item.employee_id}"
                            ),
                            "content": file_item.content,
                            "employee_id": item.employee_id,
                            "can_write": True,
                        }
                    )

            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "data_dir": container.storage_service.data_root(normalized_user_id),
                        "tree": container.storage_service.list_data_paths(normalized_user_id),
                        "files": files_payload,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/users/{user_id}/files/content")
    async def get_file_content(
        user_id: str = FastAPIPath(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """读取用户目录中的文本文件内容。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            content = container.storage_service.read_text_file(normalized_user_id, path)
            return JSONResponse(success_response(request_id=request_id, data={"path": path, "content": content}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.put("/users/{user_id}/files/content")
    async def update_file_content(
        body: FileContentUpdateBody,
        user_id: str = FastAPIPath(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """更新用户目录中的文本文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            latest = container.storage_service.write_text_file(
                normalized_user_id,
                path,
                body.content,
                body.mode,
            )
            return JSONResponse(success_response(request_id=request_id, data={"path": path, "content": latest}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.delete("/users/{user_id}/files/content")
    async def delete_file(
        user_id: str = FastAPIPath(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """删除用户目录中的文件（受白名单限制）。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            container.storage_service.delete_user_file(normalized_user_id, path)
            return JSONResponse(success_response(request_id=request_id, data={"deleted": True, "path": path}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/users/{user_id}/files/preview")
    async def preview_file(
        user_id: str = FastAPIPath(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> FileResponse:
        """预览用户目录中的图片文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            abs_path = container.storage_service.resolve_data_file_path(
                normalized_user_id,
                path,
                access_mode="read",
                access_scope="user",
            )
            suffix = Path(abs_path).suffix.lower()
            if suffix not in PREVIEWABLE_IMAGE_SUFFIXES:
                raise ValidationError(f"仅支持图片预览：{path}")
            media_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
            return FileResponse(path=abs_path, media_type=media_type)
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/users/{user_id}/files/brand-library")
    async def upload_brand_library_files(
        files: list[UploadFile] = File(...),
        user_id: str = FastAPIPath(..., min_length=1),
    ) -> JSONResponse:
        """上传一个或多个文件到 `brand_library`。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_id(user_id)
            brand_library_dir = user_brand_library_dir(normalized_user_id).resolve()
            brand_library_dir.mkdir(parents=True, exist_ok=True)
            if not files:
                raise ValidationError("请至少选择一个文件")

            uploaded: list[dict[str, Any]] = []
            for upload in files:
                try:
                    original_name = container.storage_service.normalize_upload_file_name(upload.filename or "")
                    original_target_path = (brand_library_dir / original_name).resolve()
                    # 双重路径校验：既允许直接落在根目录，也允许其子目录，不允许跳出 brand_library。
                    if original_target_path != brand_library_dir and brand_library_dir not in original_target_path.parents:
                        raise ValidationError("上传文件路径非法")
                    name_conflicted = original_target_path.exists()

                    final_name = original_name
                    if name_conflicted:
                        # 命名冲突时自动重命名，保留原文件且保证本次上传可落盘。
                        final_name = container.storage_service.deduplicate_file_name(brand_library_dir, original_name)

                    target_path = (brand_library_dir / final_name).resolve()
                    if target_path != brand_library_dir and brand_library_dir not in target_path.parents:
                        raise ValidationError("上传文件路径非法")
                    payload = await upload.read()
                    target_path.write_bytes(payload)
                    uploaded.append(
                        {
                            "file_name": final_name,
                            "original_file_name": original_name,
                            "renamed": final_name != original_name,
                            "path": f"brand_library/{final_name}",
                            "size": len(payload),
                            "name_conflicted": name_conflicted,
                        }
                    )
                finally:
                    await upload.close()

            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"uploaded": uploaded, "count": len(uploaded)},
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/users/{user_id}/employees/{employee_id}/sessions/{session_id}/messages/stream")
    async def stream_messages(
        body: ChatStreamBody,
        background_tasks: BackgroundTasks,
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
        session_id: str = FastAPIPath(..., min_length=1),
    ) -> StreamingResponse:
        """SSE 流式聊天入口。"""
        request_id = new_request_id()
        normalized_user_id, normalized_employee_id, actual_session_id = await _resolve_employee(
            container,
            user_id=user_id,
            employee_id=employee_id,
            auto_create_default=True,
        )
        _ensure_session_binding(normalized_employee_id, session_id)
        if session_id != actual_session_id:
            raise raise_http(
                ValidationError(
                    f"session_id 无效：期望 {actual_session_id}，实际 {session_id}",
                ),
                request_id,
            )

        await container.storage_service.ensure_employee_files(normalized_user_id, normalized_employee_id)
        llm_config = await container.settings_service.get_llm_config(normalized_user_id)
        max_tool_rounds = llm_config.max_tool_rounds or FIXED_MAX_TOOL_ROUNDS

        async def event_stream() -> AsyncIterator[str]:
            """构造 SSE 事件流并逐步产出事件。"""
            builder = SSEEnvelopeBuilder(
                request_id=request_id,
                employee_id=normalized_employee_id,
                session_id=actual_session_id,
            )
            yield builder.frame(
                "meta",
                {
                    "user_id": normalized_user_id,
                    "employee_id": normalized_employee_id,
                    "session_id": actual_session_id,
                    "model": llm_config.model,
                    "max_tool_rounds": max_tool_rounds,
                },
            )

            # 用队列桥接“服务内部异步事件”与“HTTP SSE 推流”。
            event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def forward_agent_event(event: dict[str, Any]) -> None:
                """把 Agent 事件转发到 SSE 队列。"""
                await event_queue.put(dict(event))

            process_task = asyncio.create_task(
                container.agent_service.stream_chat(
                    user_id=normalized_user_id,
                    employee_id=normalized_employee_id,
                    session_id=actual_session_id,
                    user_message=body.message,
                    llm_config=llm_config,
                    on_event=forward_agent_event,
                )
            )

            async def drain_queue() -> list[dict[str, Any]]:
                """在任务结束时把残留事件全部刷出，防止丢事件。"""
                pending: list[dict[str, Any]] = []
                while not event_queue.empty():
                    pending.append(event_queue.get_nowait())
                return pending

            async def cancel_task_silently(task: asyncio.Task[Any]) -> None:
                """在异常时静默取消后台任务，避免未处理取消异常污染日志。"""
                if task.done():
                    return
                task.cancel()
                try:
                    await task
                except Exception:  # noqa: BLE001
                    pass

            def map_event(raw_event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
                """将内部事件映射为前端消费的 SSE 事件类型。"""
                event_name = str(raw_event.get("event") or "").strip().lower()
                if event_name in {
                    "graph_reasoning_start",
                    "graph_reasoning_end",
                    "graph_tool_start",
                    "graph_tool_end",
                    "graph_error",
                }:
                    return event_name, raw_event

                # 屏蔽内部事件（旧协议或非公开事件），避免污染外部 SSE 协议。
                if event_name == "meta":
                    return "", raw_event

                return "system_event", raw_event

            try:
                while not process_task.done():
                    try:
                        # 采用短超时轮询，兼顾及时推流与“任务已结束”状态检测。
                        event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        continue
                    event_type, payload = map_event(event)
                    if not event_type:
                        continue
                    yield builder.frame(event_type, payload)

                result = await process_task

                for event in await drain_queue():
                    event_type, payload = map_event(event)
                    if not event_type:
                        continue
                    yield builder.frame(event_type, payload)

                yield builder.frame("assistant_final", {"content": result.assistant_text, "usage": result.usage or {}})

                # 达到阈值后只后台触发压缩，不阻塞当前响应链路。
                if result.compression_scheduled:
                    background_tasks.add_task(
                        container.agent_service.compress_session_memory,
                        user_id=normalized_user_id,
                        employee_id=normalized_employee_id,
                        session_id=actual_session_id,
                        llm_config=llm_config,
                    )
                    yield builder.frame("meta", {"compression_scheduled": True, "reason": "触发token阈值"})

                yield builder.frame("memory_status", asdict(result.status))
                yield builder.frame("done", {"ok": True})
            except Exception as exc:  # noqa: BLE001
                for event in await drain_queue():
                    event_type, payload = map_event(event)
                    if not event_type:
                        continue
                    yield builder.frame(event_type, payload)
                await cancel_task_silently(process_task)
                yield builder.frame("error", {"message": f"请求处理失败：{exc}"})
                yield builder.frame("done", {"ok": False})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            background=background_tasks,
        )

    @router.get("/users/{user_id}/employees/{employee_id}/sessions/{session_id}/memory")
    async def get_memory_status(
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
        session_id: str = FastAPIPath(..., min_length=1),
        model: str | None = Query(default=None),
    ) -> JSONResponse:
        """查询会话记忆状态。"""
        request_id = new_request_id()
        try:
            normalized_user_id, normalized_employee_id, actual_session_id = await _resolve_employee(
                container,
                user_id=user_id,
                employee_id=employee_id,
                auto_create_default=True,
            )
            _ensure_session_binding(normalized_employee_id, session_id)
            if session_id != actual_session_id:
                raise ValidationError(f"session_id 无效：期望 {actual_session_id}，实际 {session_id}")
            await container.storage_service.ensure_employee_files(normalized_user_id, normalized_employee_id)
            if model:
                model_name = str(model).strip() or "agent-advoo"
            else:
                model_name = (await container.settings_service.get_settings(normalized_user_id)).model
            status = await container.agent_service.get_memory_status(
                user_id=normalized_user_id,
                employee_id=normalized_employee_id,
                session_id=actual_session_id,
                model=model_name,
            )
            return JSONResponse(success_response(request_id=request_id, data=status))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/users/{user_id}/employees/{employee_id}/sessions/{session_id}/compressions")
    async def create_compression(
        background_tasks: BackgroundTasks,
        user_id: str = FastAPIPath(..., min_length=1),
        employee_id: str = FastAPIPath(..., min_length=1),
        session_id: str = FastAPIPath(..., min_length=1),
    ) -> JSONResponse:
        """手动触发会话压缩任务（后台执行）。"""
        request_id = new_request_id()
        try:
            normalized_user_id, normalized_employee_id, actual_session_id = await _resolve_employee(
                container,
                user_id=user_id,
                employee_id=employee_id,
                auto_create_default=True,
            )
            _ensure_session_binding(normalized_employee_id, session_id)
            if session_id != actual_session_id:
                raise ValidationError(f"session_id 无效：期望 {actual_session_id}，实际 {session_id}")
            await container.storage_service.ensure_employee_files(normalized_user_id, normalized_employee_id)

            llm_config = await container.settings_service.get_llm_config(normalized_user_id)

            accepted = await container.agent_service.try_start_manual_compression(
                user_id=normalized_user_id,
                session_id=actual_session_id,
            )
            if accepted:
                background_tasks.add_task(
                    container.agent_service.compress_session_memory,
                    user_id=normalized_user_id,
                    employee_id=normalized_employee_id,
                    session_id=actual_session_id,
                    llm_config=llm_config,
                )
            # 即使未抢占成功（通常是已有压缩在跑），仍返回当前状态供前端刷新展示。
            status = await container.agent_service.get_memory_status(
                user_id=normalized_user_id,
                employee_id=normalized_employee_id,
                session_id=actual_session_id,
                model=llm_config.model,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "accepted": accepted,
                        "user_id": normalized_user_id,
                        "employee_id": normalized_employee_id,
                        "session_id": actual_session_id,
                        "is_compressing": status.is_compressing,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    return router
