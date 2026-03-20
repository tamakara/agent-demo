"""agent-demo 的 FastAPI 启动入口。

该文件只承担三类职责：
1. 应用生命周期管理（启动时构建容器，关闭时释放资源）。
2. 静态资源挂载（前端页面及 JS/CSS）。
3. 全局异常兜底，统一输出标准错误响应。

注意：
- 这里不包含任何业务逻辑；业务逻辑都在 app 层服务中。
- 这里也不直接实例化基础设施依赖，统一交给 api.dependencies.build_container。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import build_container
from api.response import error_response
from api.routes import create_router
from app.errors import AppError


# 前端静态目录：用于挂载 /static 以及主页 index.html。
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期钩子。

    启动阶段：
    - 构建依赖容器（包含 app/infra 所需组件）。
    - 注册路由。

    关闭阶段：
    - 显式关闭 SQLite 连接，避免进程退出时资源未释放。
    """
    container = await build_container()
    app.state.container = container
    app.include_router(create_router(container))
    try:
        yield
    finally:
        await container.sqlite_repo.close()


def _request_id_from_request(request: Request) -> str:
    """提取请求追踪 ID。

    优先读取客户端传入的 `x-request-id`，
    若未提供则生成一个随机 ID，确保每个响应都可追踪。
    """
    return str(request.headers.get("x-request-id") or uuid4().hex)


# 应用对象：版本号在重大架构调整时递增，方便排障时识别部署版本。
app = FastAPI(title="agent-demo", version="3.0.0", lifespan=lifespan)

# 仅当静态目录存在时才挂载，便于后端单独运行的场景。
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_model=None)
async def index() -> Any:
    """主页入口。

    - 若前端静态页面存在：返回 index.html。
    - 若静态资源缺失：返回简单 JSON，确认后端已启动。
    """
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "agent-demo backend running"})


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """处理应用层显式抛出的业务异常。"""
    request_id = _request_id_from_request(request)
    payload = error_response(request_id=request_id, error=exc)
    return JSONResponse(payload, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """处理 FastAPI/路由层抛出的 HTTPException。

    规则：
    - 如果下游已经构造了标准错误体（带 request_id/error），直接透传。
    - 否则包装成 AppError 后输出统一结构。
    """
    if isinstance(exc.detail, dict) and "request_id" in exc.detail and "error" in exc.detail:
        return JSONResponse(exc.detail, status_code=exc.status_code)

    request_id = _request_id_from_request(request)
    wrapped = AppError(
        code="http_error",
        message=str(exc.detail),
        status_code=exc.status_code,
        details=exc.detail,
    )
    payload = error_response(request_id=request_id, error=wrapped)
    return JSONResponse(payload, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """处理请求参数校验失败（422）。"""
    request_id = _request_id_from_request(request)
    wrapped = AppError(
        code="validation_error",
        message="请求参数校验失败",
        status_code=422,
        details=exc.errors(),
    )
    payload = error_response(request_id=request_id, error=wrapped)
    return JSONResponse(payload, status_code=422)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理。

    任何未被前面分支捕获的异常都会走这里，
    统一转为 500，防止把内部堆栈直接暴露给客户端。
    """
    request_id = _request_id_from_request(request)
    wrapped = AppError(
        code="internal_error",
        message="服务内部错误",
        status_code=500,
        details=str(exc),
    )
    payload = error_response(request_id=request_id, error=wrapped)
    return JSONResponse(payload, status_code=500)
