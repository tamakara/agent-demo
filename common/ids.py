"""通用 ID 处理工具。"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from common.errors import ValidationError


USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def normalize_user_id(user_id: str) -> str:
    """校验并标准化 user_id。"""
    candidate = str(user_id or "").strip()
    if not candidate:
        raise ValidationError("user_id 不能为空")
    if not USER_ID_PATTERN.fullmatch(candidate):
        raise ValidationError("user_id 仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头")
    return candidate


def new_session_id() -> str:
    """生成 session id。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid4().hex[:6]
    return f"session-{timestamp}-{suffix}"

