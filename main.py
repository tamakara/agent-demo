"""agent-demo FastAPI 入口。"""

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
from api.routes import create_router
from common.errors import AppError
from common.response import error_response


STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在应用生命周期内初始化并释放全局依赖。"""
    container = await build_container()
    app.state.container = container
    app.include_router(create_router(container))
    try:
        yield
    finally:
        await container.sqlite_repo.close()


def _request_id_from_request(request: Request) -> str:
    """从请求头读取 request_id，不存在时生成一个。"""
    return str(request.headers.get("x-request-id") or uuid4().hex)


app = FastAPI(title="agent-demo", version="2.0.0", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_model=None)
async def index() -> Any:
    """返回前端主页；若静态资源缺失则返回健康提示。"""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "agent-demo backend running"})


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """统一处理应用层显式抛出的业务异常。"""
    request_id = _request_id_from_request(request)
    payload = error_response(request_id=request_id, error=exc)
    return JSONResponse(payload, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """统一处理 FastAPI ``HTTPException`` 异常。"""
    if isinstance(exc.detail, dict) and {"request_id", "ts"}.issubset(set(exc.detail.keys())):
        # 若下游已经构造了标准响应，则直接透传。
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
    """处理请求参数校验失败错误。"""
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
    """兜底处理未捕获异常，避免泄漏堆栈到客户端。"""
    request_id = _request_id_from_request(request)
    wrapped = AppError(
        code="internal_error",
        message="服务内部错误",
        status_code=500,
        details=str(exc),
    )
    payload = error_response(request_id=request_id, error=wrapped)
    return JSONResponse(payload, status_code=500)
