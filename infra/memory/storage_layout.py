"""本地记忆存储目录布局与路径校验。"""

from __future__ import annotations

import re
from pathlib import Path

from common.ids import normalize_employee_id
from common.errors import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
USERS_DIR = DATA_DIR / "user"
EMPLOYEE_SUBDIR = "employee"
EMPLOYEE_ONE = "1"
NOTEBOOK_SUBDIR = "notebook"
WORKSPACE_SUBDIR = "workspace"
SKILLS_SUBDIR = "skills"
BRAND_LIBRARY_SUBDIR = "brand_library"
SKILL_LIBRARY_SUBDIR = "skill_library"
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

ASSET_PLACEHOLDER_FILE = "file.md"
PERSONA_FILE = "soul.md"
SCHEDULE_FILE = "schedule.md"
WORKBOOK_FILE = "workbook.md"
COMPRESSED_MEMORY_FILE = "memory.md"

# 已知文件名固定映射到 employee/{id} 指定位置；未知 .md 默认落到 notebook/。
MEMORY_FILE_LOCATIONS_UNDER_EMPLOYEE: dict[str, Path] = {
    COMPRESSED_MEMORY_FILE: Path(COMPRESSED_MEMORY_FILE),
    ASSET_PLACEHOLDER_FILE: Path(NOTEBOOK_SUBDIR) / ASSET_PLACEHOLDER_FILE,
    SCHEDULE_FILE: Path(NOTEBOOK_SUBDIR) / SCHEDULE_FILE,
    PERSONA_FILE: Path(NOTEBOOK_SUBDIR) / PERSONA_FILE,
    WORKBOOK_FILE: Path(NOTEBOOK_SUBDIR) / WORKBOOK_FILE,
}


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


def user_employee_dir(user_id: str) -> Path:
    """返回用户 employee 根目录。"""
    return user_root_dir(user_id) / EMPLOYEE_SUBDIR


def user_employee_member_dir(user_id: str, employee_id: str) -> Path:
    """返回指定员工目录。"""
    return user_employee_dir(user_id) / normalize_employee_id(employee_id)


def user_employee_notebook_dir(user_id: str, employee_id: str) -> Path:
    """返回指定员工 notebook 目录。"""
    return user_employee_member_dir(user_id, employee_id) / NOTEBOOK_SUBDIR


def user_employee_workspace_dir(user_id: str, employee_id: str) -> Path:
    """返回指定员工 workspace 目录。"""
    return user_employee_member_dir(user_id, employee_id) / WORKSPACE_SUBDIR


def user_employee_skills_dir(user_id: str, employee_id: str) -> Path:
    """返回指定员工 skills 目录。"""
    return user_employee_member_dir(user_id, employee_id) / SKILLS_SUBDIR


def user_employee_memory_file(user_id: str, employee_id: str = EMPLOYEE_ONE) -> Path:
    """返回指定员工的压缩记忆文件路径（memory.md）。"""
    return user_employee_member_dir(user_id, employee_id) / COMPRESSED_MEMORY_FILE


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


def resolve_memory_relative_path(file_name: str) -> Path:
    """解析记忆文件在员工目录中的相对路径。"""
    valid_name = validate_file_name(file_name)
    return MEMORY_FILE_LOCATIONS_UNDER_EMPLOYEE.get(
        valid_name,
        Path(NOTEBOOK_SUBDIR) / valid_name,
    )


def resolve_memory_path(*, user_id: str, employee_id: str, file_name: str) -> Path:
    """解析用户记忆文件绝对路径，并防止目录穿越。"""
    employee_dir = user_employee_member_dir(user_id, employee_id).resolve()
    relative = resolve_memory_relative_path(file_name)
    target = (employee_dir / relative).resolve()
    base = employee_dir
    if base not in target.parents and target != base:
        raise ValidationError("记忆文件路径非法")
    return target
