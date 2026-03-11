"""统一响应结构构建工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.errors import AppError
from common.time_utils import utc_now_iso


@dataclass(slots=True)
class ResponseEnvelope:
    """统一 API 响应信封。"""
    request_id: str
    ts: str
    data: Any | None = None
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """输出标准字典结构。"""
        payload: dict[str, Any] = {
            "request_id": self.request_id,
            "ts": self.ts,
        }
        if self.error is not None:
            payload["error"] = self.error
        else:
            payload["data"] = self.data
        return payload


def success_response(*, request_id: str, data: Any) -> dict[str, Any]:
    """构建成功响应。"""
    return ResponseEnvelope(request_id=request_id, ts=utc_now_iso(), data=data).as_dict()


def error_response(*, request_id: str, error: AppError) -> dict[str, Any]:
    """构建错误响应。"""
    return ResponseEnvelope(
        request_id=request_id,
        ts=utc_now_iso(),
        error={
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    ).as_dict()
