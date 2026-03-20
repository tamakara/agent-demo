"""Application-level error types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: Any | None = None

    def __str__(self) -> str:
        return self.message


class NotFoundError(AppError):
    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(code="not_found", message=message, status_code=404, details=details)


class ValidationError(AppError):
    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(code="validation_error", message=message, status_code=400, details=details)


class InternalError(AppError):
    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(code="internal_error", message=message, status_code=500, details=details)
