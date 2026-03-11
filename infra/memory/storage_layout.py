"""本地记忆存储目录布局与路径校验。"""

from __future__ import annotations

import re
from pathlib import Path

from common.errors import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
USERS_DIR = DATA_DIR / "user"
MEMORY_SUBDIR = "memory"
BRAND_LIBRARY_SUBDIR = "brand_library"
SKILL_LIBRARY_SUBDIR = "skill_library"
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SYSTEM_PROMPT_FILE = "系统提示词.md"
ASSET_PLACEHOLDER_FILE = "素材库记忆.md"


def validate_user_id(user_id: str) -> str:
    """校验并返回规范化后的 ``user_id``。"""
    if not isinstance(user_id, str):
        raise ValidationError("user_id 必须是字符串")
    normalized = user_id.strip()
    if not normalized:
        raise ValidationError("user_id 不能为空")
    if not USER_ID_PATTERN.fullmatch(normalized):
        raise ValidationError("user_id 仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头")
    return normalized


def user_root_dir(user_id: str) -> Path:
    """返回用户根目录，并防止目录逃逸。"""
    valid_user_id = validate_user_id(user_id)
    base_dir = USERS_DIR.resolve()
    target = (USERS_DIR / valid_user_id).resolve()
    if target == base_dir or base_dir not in target.parents:
        raise ValidationError("user_id 对应目录非法")
    return target


def user_memory_dir(user_id: str) -> Path:
    """返回用户记忆目录。"""
    return user_root_dir(user_id) / MEMORY_SUBDIR


def user_brand_library_dir(user_id: str) -> Path:
    """返回用户品牌素材目录。"""
    return user_root_dir(user_id) / BRAND_LIBRARY_SUBDIR


def user_skill_library_dir(user_id: str) -> Path:
    """返回用户技能素材目录。"""
    return user_root_dir(user_id) / SKILL_LIBRARY_SUBDIR


def validate_file_name(file_name: str) -> str:
    """校验记忆文件名，仅允许 ``.md`` 文件名。"""
    if not isinstance(file_name, str):
        raise ValidationError("file_name 必须是字符串")
    name = file_name.strip()
    if not name:
        raise ValidationError("file_name 不能为空")
    if "/" in name or "\\" in name:
        raise ValidationError("file_name 必须是文件名，不能包含路径")
    if not name.endswith(".md"):
        raise ValidationError("仅支持 .md 文件")
    return name


def resolve_memory_path(*, user_id: str, file_name: str) -> Path:
    """解析用户记忆文件绝对路径，并防止目录穿越。"""
    valid_name = validate_file_name(file_name)
    user_dir = user_memory_dir(user_id)
    base = user_dir.resolve()
    target = (user_dir / valid_name).resolve()
    if base not in target.parents and target != base:
        raise ValidationError("记忆文件路径非法")
    return target
