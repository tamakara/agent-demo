"""API 路由共享工具函数。"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from api.dependencies import AppContainer
from common.errors import AppError, ValidationError
from common.ids import normalize_employee_id, normalize_user_id
from common.response import error_response


FIXED_MAX_TOOL_ROUNDS = 64
PREVIEWABLE_IMAGE_SUFFIXES = {".png", ".jpeg", ".jpg", ".webp", ".gif", ".bmp", ".svg"}
EDITABLE_TEXT_SUFFIXES = {".md", ".txt"}
DELETABLE_DATA_ROOTS = {"brand_library", "skill_library"}
DUPLICATE_NAME_SUFFIX_PATTERN = re.compile(r"^(?P<base>.*?)(?:\((?P<idx>\d+)\)|（(?P<idx_cn>\d+)）)$")


def new_request_id() -> str:
    """生成请求级追踪 ID。"""
    return uuid4().hex


def raise_http(error: AppError, request_id: str) -> HTTPException:
    """将应用异常转换为 HTTPException，并保持统一响应结构。"""
    return HTTPException(status_code=error.status_code, detail=error_response(request_id=request_id, error=error))


def memory_status_to_dict(status: Any) -> dict[str, Any]:
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


def normalize_upload_file_name(file_name: str) -> str:
    """规范化上传文件名并限制为单文件名。"""
    raw = str(file_name or "").strip()
    if not raw:
        raise ValidationError("上传文件名不能为空")
    name = Path(raw).name.strip()
    if not name or name in {".", ".."}:
        raise ValidationError("上传文件名非法")
    if len(name) > 255:
        raise ValidationError("上传文件名过长（最多 255 个字符）")
    return name


def deduplicate_file_name(base_dir: Path, file_name: str) -> str:
    """若同名文件已存在，则生成 ``name(n).ext`` 可用文件名。"""
    candidate = Path(file_name)
    stem = candidate.stem
    suffix = candidate.suffix

    matched = DUPLICATE_NAME_SUFFIX_PATTERN.fullmatch(stem)
    if matched:
        base_stem = str(matched.group("base") or "").strip()
        index_raw = matched.group("idx") or matched.group("idx_cn") or "0"
        start_index = max(1, int(index_raw) + 1)
        if not base_stem:
            base_stem = stem
            start_index = 1
    else:
        base_stem = stem
        start_index = 1

    index = start_index
    while True:
        renamed = f"{base_stem}({index}){suffix}"
        target_path = (base_dir / renamed).resolve()
        if not target_path.exists():
            return renamed
        index += 1


def data_root_from_tree_path(path: str) -> str:
    """返回目录树路径的一级目录名。"""
    parts = [part for part in str(path or "").strip().split("/") if part]
    return parts[0] if parts else ""


def normalize_user_path(user_id: str) -> str:
    """规范化路径参数中的 ``user_id``。"""
    return normalize_user_id(user_id)


def normalize_employee_path(employee_id: str | None, *, default: str = "1") -> str:
    """规范化路径参数中的 ``employee_id``。"""
    return normalize_employee_id(employee_id, default=default)


async def resolve_employee(
    container: AppContainer,
    *,
    user_id: str,
    employee_id: str | None,
    auto_create_default: bool = True,
) -> tuple[str, str]:
    """解析并校验员工身份，返回 ``(employee_id, session_id)``。"""
    normalized_employee_id = normalize_employee_path(employee_id, default="1")
    employee = await container.employee_service.get_employee(
        user_id,
        normalized_employee_id,
        auto_create_default=auto_create_default,
    )
    return employee.employee_id, employee.session_id

