"""API 响应封装工具。

统一响应格式：
- 成功：{request_id, ts, data}
- 失败：{request_id, ts, error}

这样可保证前后端在日志追踪、错误处理上保持一致协议。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from app.errors import AppError
from api.time_utils import utc_now_iso


@dataclass(slots=True)
class ResponseEnvelope:
    """统一响应信封对象。"""

    request_id: str
    ts: str
    data: Any | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """输出可直接 JSON 序列化的标准字典。"""
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            "ts": self.ts,
        }
        if self.error is not None:
            payload["error"] = self.error
        else:
            payload["data"] = serialize_value(self.data)
        return payload


def serialize_value(value: Any) -> Any:
    """递归序列化 dataclass/list/dict，便于统一输出。"""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    return value


def success_response(*, request_id: str, data: Any) -> dict[str, Any]:
    """构造成功响应体。"""
    return ResponseEnvelope(request_id=request_id, ts=utc_now_iso(), data=data).as_dict()


def error_response(*, request_id: str, error: AppError) -> dict[str, Any]:
    """构造失败响应体。"""
    return ResponseEnvelope(
        request_id=request_id,
        ts=utc_now_iso(),
        error={
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    ).as_dict()
