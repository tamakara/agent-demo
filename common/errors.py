"""通用错误定义与异常模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    """应用层统一错误模型。"""

    code: str
    message: str
    status_code: int = 400
    details: Any | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        """返回当前异常的可读字符串。"""
        return self.message


class NotFoundError(AppError):
    """资源不存在。"""

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        """构造 404 资源不存在错误。"""
        super().__init__(code="not_found", message=message, status_code=404, details=details)


class ValidationError(AppError):
    """请求参数不合法。"""

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        """构造 400 参数校验错误。"""
        super().__init__(code="validation_error", message=message, status_code=400, details=details)


class InternalError(AppError):
    """内部异常。"""

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        """构造 500 内部错误。"""
        super().__init__(code="internal_error", message=message, status_code=500, details=details)
