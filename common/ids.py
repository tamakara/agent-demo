"""通用 ID 处理工具。"""

from __future__ import annotations

import re

from common.errors import ValidationError


USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EMPLOYEE_ID_PATTERN = re.compile(r"^[1-9][0-9]{0,8}$")
EMPLOYEE_SESSION_ID_PATTERN = re.compile(r"^employee-([1-9][0-9]{0,8})$")


def normalize_user_id(user_id: str) -> str:
    """校验并标准化 user_id。"""
    candidate = str(user_id or "").strip()
    if not candidate:
        raise ValidationError("user_id 不能为空")
    if not USER_ID_PATTERN.fullmatch(candidate):
        raise ValidationError("user_id 仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头")
    return candidate


def normalize_employee_id(employee_id: str | int | None, *, default: str = "1") -> str:
    """校验并标准化 employee_id。"""
    candidate = str(employee_id or "").strip() or default
    if not EMPLOYEE_ID_PATTERN.fullmatch(candidate):
        raise ValidationError("employee_id 必须是正整数字符串，例如 1、2、3")
    return candidate


def session_id_from_employee_id(employee_id: str | int) -> str:
    """根据员工编号生成稳定的 session_id。"""
    normalized = normalize_employee_id(employee_id)
    return f"employee-{normalized}"


def employee_id_from_session_id(session_id: str | None) -> str | None:
    """从 session_id 解析员工编号；不匹配则返回 ``None``。"""
    candidate = str(session_id or "").strip()
    if not candidate:
        return None
    matched = EMPLOYEE_SESSION_ID_PATTERN.fullmatch(candidate)
    if matched is None:
        return None
    return matched.group(1)

