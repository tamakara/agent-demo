"""agent-demo 的 FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.db import SQLiteStore
from core.memory_manager import MemoryManager
from core.models import (
    ChatRequest,
    FlushRequest,
    FlushResponse,
    GlobalLLMConfig,
    MemoryFileEntry,
    MemoryFilesResponse,
    MemoryFileUpdateRequest,
    MemoryStatusResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionEntry,
    SessionListResponse,
    SessionMessageEntry,
    SessionMessagesResponse,
)
from core.tools import (
    ensure_memory_files_exist,
    list_memory_file_names,
    read_memory_file_impl,
    reset_memory_to_initial_content,
    write_memory_file_impl,
)


db = SQLiteStore()
memory_manager = MemoryManager(db)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期管理。

    启动阶段：
    1) 初始化 SQLite（建库/建表/建索引）。

    关闭阶段：
    1) 关闭数据库连接。
    """
    await db.initialize()
    try:
        yield
    finally:
        await db.close()


app = FastAPI(title="agent-demo", version="1.0.0", lifespan=lifespan)

# 静态资源目录：仅在目录存在时挂载，避免纯后端场景启动报错。
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _sse(event: str, data: dict[str, Any]) -> str:
    """将事件字典编码成 SSE 文本帧。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _event_name(event: dict[str, Any]) -> str:
    """统一解析事件名，缺失时回退到 tool_event。"""
    return str(event.get("event") or "tool_event")


def _event_to_sse(event: dict[str, Any]) -> str:
    """把内部事件对象转为可直接发送的 SSE 字符串。"""
    return _sse(_event_name(event), event)


def _drain_event_queue(event_queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    """一次性取出队列中的全部待发送事件，保证结束/异常时不丢尾帧。"""
    pending: list[dict[str, Any]] = []
    while not event_queue.empty():
        pending.append(event_queue.get_nowait())
    return pending


async def _cancel_task_silently(task: asyncio.Task[Any]) -> None:
    """尽力取消后台任务；取消阶段的异常在这里吞掉，避免污染接口响应。"""
    if task.done():
        return
    task.cancel()
    try:
        await task
    except Exception:  # noqa: BLE001
        pass


def _build_session_entry(data: dict[str, Any]) -> SessionEntry:
    """数据库行 -> SessionEntry，统一做类型兜底，降低脏数据对接口层影响。"""
    return SessionEntry(
        user_id=str(data.get("user_id", "")),
        session_id=str(data.get("session_id", "")),
        is_flushing=bool(data.get("is_flushing", False)),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        message_count=int(data.get("message_count", 0)),
    )


def _build_session_message_entry(data: dict[str, Any]) -> SessionMessageEntry:
    """数据库行 -> SessionMessageEntry。"""
    return SessionMessageEntry(
        id=int(data.get("id", 0)),
        user_id=str(data.get("user_id", "")),
        session_id=str(data.get("session_id", "")),
        role=str(data.get("role", "")),
        content=str(data.get("content", "")),
        zone=str(data.get("zone", "")),
        created_at=str(data.get("created_at", "")),
    )


def _new_session_id() -> str:
    """生成可读且基本唯一的会话 ID：session-时间戳-随机后缀。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"session-{timestamp}-{suffix}"


def _require_user_id(user_id: str) -> str:
    """统一做 user_id 的字符串收敛，避免空白值透传。"""
    normalized = str(user_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    if not USER_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="user_id 仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头",
        )
    return normalized


async def _ensure_user_memory_files(user_id: str) -> str:
    """按需初始化指定用户的记忆目录。"""
    normalized = _require_user_id(user_id)
    try:
        await ensure_memory_files_exist(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return normalized


async def _collect_memory_files(user_id: str) -> list[MemoryFileEntry]:
    """
    读取当前可管理的全部记忆文件。

    说明：
    - 文件列表来自 list_memory_file_names()（受工具层白名单控制）。
    - 某个文件缺失时返回空字符串，避免前端因单文件异常导致整页失败。
    """
    files: list[MemoryFileEntry] = []
    for file_name in list_memory_file_names(user_id):
        try:
            content = await read_memory_file_impl(user_id=user_id, file_name=file_name)
        except FileNotFoundError:
            content = ""
        files.append(MemoryFileEntry(file_name=file_name, content=content))
    return files


@app.get("/", response_model=None)
async def index() -> Any:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "agent-demo 后端服务运行中"})


@app.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions(user_id: str = Query(..., min_length=1)) -> SessionListResponse:
    normalized_user_id = _require_user_id(user_id)
    rows = await db.list_sessions(normalized_user_id, limit=300)
    entries = [_build_session_entry(row) for row in rows]
    return SessionListResponse(sessions=entries)


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session(request: SessionCreateRequest) -> SessionCreateResponse:
    user_id = _require_user_id(request.user_id)
    # 优先使用请求里传入的 ID；若为空则自动生成。
    session_id = (request.session_id or "").strip() or _new_session_id()
    # SQLiteStore.create_session 已包含“创建后读取”，不再重复查询。
    session = await db.create_session(user_id, session_id)
    entry = _build_session_entry({**session, "message_count": 0})
    return SessionCreateResponse(created=True, session=entry)


@app.get("/api/session-messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    user_id: str = Query(..., min_length=1),
    session_id: str = Query(..., min_length=1),
    limit: int = Query(default=500, ge=1, le=5000),
) -> SessionMessagesResponse:
    normalized_user_id = _require_user_id(user_id)
    normalized_session_id = str(session_id).strip()
    rows = await db.list_messages(
        user_id=normalized_user_id,
        session_id=normalized_session_id,
        ascending=True,
        limit=limit,
    )
    entries = [_build_session_message_entry(row) for row in rows]
    return SessionMessagesResponse(
        user_id=normalized_user_id,
        session_id=normalized_session_id,
        messages=entries,
    )


@app.get("/api/settings", response_model=GlobalLLMConfig)
async def get_global_settings(user_id: str = Query(..., min_length=1)) -> GlobalLLMConfig:
    """通用设置读取接口（包含 LLM 与上下文窗口设置）。"""
    normalized_user_id = _require_user_id(user_id)
    config = await db.get_global_llm_config(normalized_user_id)
    return GlobalLLMConfig(**config)


@app.put("/api/settings", response_model=GlobalLLMConfig)
async def update_global_settings(config: GlobalLLMConfig, user_id: str = Query(..., min_length=1)) -> GlobalLLMConfig:
    """通用设置更新接口（包含 LLM 与上下文窗口设置）。"""
    normalized_user_id = _require_user_id(user_id)
    await db.update_global_llm_config(
        user_id=normalized_user_id,
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        max_tool_rounds=config.max_tool_rounds,
        total_token_limit=config.total_token_limit,
    )
    latest = await db.get_global_llm_config(normalized_user_id)
    return GlobalLLMConfig(**latest)


@app.post("/api/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> StreamingResponse:
    normalized_user_id = await _ensure_user_memory_files(request.user_id)
    normalized_session_id = str(request.session_id).strip()

    async def event_stream() -> AsyncIterator[str]:
        # 首帧先发元信息，前端可立即知道当前会话和模型配置。
        yield _sse(
            "meta",
            {
                "user_id": normalized_user_id,
                "session_id": normalized_session_id,
                "model": request.llm_config.model,
                "max_tool_rounds": request.max_tool_rounds,
            },
        )
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def _forward_agent_event(event: dict[str, Any]) -> None:
            # 运行中的工具事件先进入队列；队列机制让“生成事件”和“发送事件”解耦。
            await event_queue.put(dict(event))

        process_task = asyncio.create_task(
            memory_manager.process_chat(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                user_message=request.message,
                llm_config=request.llm_config,
                max_tool_rounds=request.max_tool_rounds,
                on_event=_forward_agent_event,
            )
        )
        try:
            # 主循环：任务未结束时，持续轮询队列并实时推送事件。
            while not process_task.done():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                yield _event_to_sse(event)

            # 任务结束后拿最终结果。
            result = await process_task

            # 结束瞬间可能还有尾帧残留在队列，统一补发。
            for event in _drain_event_queue(event_queue):
                yield _event_to_sse(event)

            # 输出模型最终文本。
            yield _sse(
                "assistant_final",
                {"content": result.assistant_text, "usage": result.usage or {}},
            )

            if result.flush_scheduled:
                # 本轮结束后异步刷盘，不阻塞当前聊天请求。
                background_tasks.add_task(
                    memory_manager.flush_session_memory,
                    normalized_user_id,
                    normalized_session_id,
                    request.llm_config,
                    request.max_tool_rounds,
                )
                yield _sse("meta", {"flush_scheduled": True, "reason": "触发token阈值"})

            # 最后输出记忆状态和 done，便于前端统一收尾。
            yield _sse("memory_status", result.status.model_dump())
            yield _sse("done", {"ok": True})
        except Exception as exc:  # noqa: BLE001
            # 错误分支也尽量把已经产出的事件发出去，保留排障上下文。
            for event in _drain_event_queue(event_queue):
                yield _event_to_sse(event)
            await _cancel_task_silently(process_task)
            yield _sse("error", {"message": f"请求处理失败：{exc}"})
            yield _sse("done", {"ok": False})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        background=background_tasks,
    )


@app.get("/api/memory/status", response_model=MemoryStatusResponse)
async def memory_status(
    user_id: str = Query(..., min_length=1),
    session_id: str = Query(default="default", min_length=1),
    model: str = Query(default="agent-advoo", min_length=1),
) -> MemoryStatusResponse:
    normalized_user_id = await _ensure_user_memory_files(user_id)
    normalized_session_id = str(session_id).strip()
    return await memory_manager.get_status(
        user_id=normalized_user_id,
        session_id=normalized_session_id,
        model=model,
    )


@app.get("/api/memory/files", response_model=MemoryFilesResponse)
async def memory_files(user_id: str = Query(..., min_length=1)) -> MemoryFilesResponse:
    normalized_user_id = await _ensure_user_memory_files(user_id)
    files = await _collect_memory_files(normalized_user_id)
    return MemoryFilesResponse(files=files)


@app.post("/api/memory/reset")
async def reset_memory_files(user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    normalized_user_id = _require_user_id(user_id)
    # 重置 memory：清空 data/user/<user_id>/memory 后用代码内置初始内容覆盖重建。
    try:
        restored_files = await reset_memory_to_initial_content(normalized_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    files = await _collect_memory_files(normalized_user_id)
    return {"ok": True, "restored_files": restored_files, "files": [f.model_dump() for f in files]}


@app.put("/api/memory/files/{file_name}")
async def update_memory_file(
    file_name: str,
    body: MemoryFileUpdateRequest,
    user_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    normalized_user_id = await _ensure_user_memory_files(user_id)
    try:
        await write_memory_file_impl(
            user_id=normalized_user_id,
            file_name=file_name,
            content=body.content,
            mode=body.mode,
            allow_system_prompt=True,
        )
        latest = await read_memory_file_impl(user_id=normalized_user_id, file_name=file_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "file_name": file_name, "content": latest}


@app.post("/api/memory/flush", response_model=FlushResponse)
async def memory_flush(request: FlushRequest, background_tasks: BackgroundTasks) -> FlushResponse:
    normalized_user_id = await _ensure_user_memory_files(request.user_id)
    normalized_session_id = str(request.session_id).strip()
    # 手动触发刷盘：若当前会话已在刷盘中，则 accepted=False，不重复调度。
    accepted = await memory_manager.try_start_manual_flush(normalized_user_id, normalized_session_id)
    if accepted:
        background_tasks.add_task(
            memory_manager.flush_session_memory,
            normalized_user_id,
            normalized_session_id,
            request.llm_config,
            request.max_tool_rounds,
        )
    status = await memory_manager.get_status(normalized_user_id, normalized_session_id, request.llm_config.model)
    return FlushResponse(
        accepted=accepted,
        user_id=normalized_user_id,
        session_id=normalized_session_id,
        is_flushing=status.is_flushing,
    )
