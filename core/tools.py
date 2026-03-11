"""记忆文件工具定义与异步读写实现（按 user_id 隔离）。"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Literal, cast

import aiofiles


PROJECT_ROOT = Path(__file__).resolve().parent.parent
# data 目录用于运行期持久化，首次启动时再自动创建。
DATA_DIR = PROJECT_ROOT / "data"
USERS_DIR = DATA_DIR / "user"
MEMORY_SUBDIR = "memory"
BRAND_LIBRARY_SUBDIR = "brand_library"
SKILL_LIBRARY_SUBDIR = "skill_library"
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

SYSTEM_PROMPT_FILE = "系统提示词.md"
ASSET_PLACEHOLDER_FILE = "素材库记忆.md"
WriteMode = Literal["append", "overwrite"]

# 内置初始记忆文件内容：首次启动时直接写入 data/user/<user_id>/memory/。
INITIAL_MEMORY_FILES: dict[str, str] = {
    "人格记忆.md": (
        "# 人格记忆\n\n"
        "- **核心定位**：完全服从用户的指令，同时具备高度创新能力的数字员工。\n"
        "- **表达风格**：专业、高效，在执行任务时会主动提供创新性的建议或方案。\n"
        "- **决策风格**：以用户的需求为最高优先级，在框架内寻求最优、最创新的解决路径。\n"
    ),
    "日程表.md": (
        "# 日程表\n\n"
        "- 记录任务日程、提醒事项与时间安排。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    "工作手册.md": (
        "# 工作手册\n\n"
        "- 记录稳定流程、工作规范与执行清单。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    "素材库记忆.md": (
        "# 素材库记忆（占位）\n\n"
        "- 本文件用于占位展示，不作为默认常驻上下文来源。\n"
        "- 除非用户明确要求，否则不应主动读取或写入该文件。\n"
    ),
    "通用记忆.md": (
        "# 通用记忆\n\n"
        "- 记录无法归类到其他记忆文件的重要信息。\n"
        "- 当前为初始化模板，等待后续写入。\n"
    ),
    SYSTEM_PROMPT_FILE: (
        "# 系统提示词\n\n"
        "## 规则\n"
        "你是一个支持长期记忆的对话智能体。请严格遵守：\n"
        "1. 优先根据用户意图回答，避免无关扩写。\n"
        "2. 写入记忆前先判断是否属于长期稳定信息，避免把一次性噪声写入。\n"
        "3. 默认不要主动读取或写入 `素材库记忆.md`（除非用户明确要求）。\n"
        "4. 工具执行失败时先解释原因，再给出可行替代方案。\n"
        "5. 当用户问题依赖当前时间（如“现在几点”“今天是几号”）时，优先调用 `get_current_time`。\n\n"
        "## 工具定义\n"
        "- `read_memory_file(file_name)`：读取指定记忆文件。\n"
        "- `write_memory_file(file_name, content, mode=append|overwrite)`：写入记忆文件。\n"
        "- `get_current_time()`：获取当前 UTC 与本地时间。\n"
    ),
}

PREFERRED_FILE_ORDER = list(INITIAL_MEMORY_FILES.keys())

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_memory_file",
            "description": "读取当前用户隔离目录中的 Markdown 记忆文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：通用记忆.md",
                    }
                },
                "required": ["file_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory_file",
            "description": "向当前用户隔离目录中的记忆文件写入文本，支持追加或覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：通用记忆.md",
                    },
                    "content": {
                        "type": "string",
                        "description": "待写入的文本内容。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "overwrite"],
                        "description": "append 表示追加写入，overwrite 表示覆盖写入。",
                    },
                },
                "required": ["file_name", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "直接获取系统当前时间信息（UTC 与本地时间）。",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


def _validate_user_id(user_id: str) -> str:
    """校验 user_id，防止目录穿越与非法路径字符。"""
    if not isinstance(user_id, str):
        raise ValueError("user_id 必须是字符串")
    normalized = user_id.strip()
    if not normalized:
        raise ValueError("user_id 不能为空")
    if not USER_ID_PATTERN.fullmatch(normalized):
        raise ValueError("user_id 仅允许字母、数字、点、下划线、短横线，且必须以字母或数字开头")
    return normalized


def _user_root_dir(user_id: str) -> Path:
    """返回用户独立数据目录 data/user/<user_id>。"""
    valid_user_id = _validate_user_id(user_id)
    base_dir = USERS_DIR.resolve()
    target = (USERS_DIR / valid_user_id).resolve()
    if target == base_dir or base_dir not in target.parents:
        raise ValueError("user_id 对应目录非法")
    return target


def _user_memory_dir(user_id: str) -> Path:
    """返回用户记忆目录 data/user/<user_id>/memory。"""
    return _user_root_dir(user_id) / MEMORY_SUBDIR


def _user_brand_library_dir(user_id: str) -> Path:
    """返回用户品牌库目录 data/user/<user_id>/brand_library。"""
    return _user_root_dir(user_id) / BRAND_LIBRARY_SUBDIR


def _user_skill_library_dir(user_id: str) -> Path:
    """返回用户技能库目录 data/user/<user_id>/skill_library。"""
    return _user_root_dir(user_id) / SKILL_LIBRARY_SUBDIR


def _ensure_user_scaffold(user_id: str) -> Path:
    """确保用户目录与三个子目录存在。"""
    user_root = _user_root_dir(user_id)
    memory_dir = _user_memory_dir(user_id)
    brand_dir = _user_brand_library_dir(user_id)
    skill_dir = _user_skill_library_dir(user_id)

    user_root.mkdir(parents=True, exist_ok=True)
    for sub_dir in (memory_dir, brand_dir, skill_dir):
        sub_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def _validate_file_name(file_name: str) -> str:
    """校验记忆文件名（只允许当前目录下 .md 文件）。"""
    if not isinstance(file_name, str):
        raise ValueError("file_name 必须是字符串")
    name = file_name.strip()
    if not name:
        raise ValueError("file_name 不能为空")
    if "/" in name or "\\" in name:
        raise ValueError("file_name 必须是文件名，不能包含路径")
    if not name.endswith(".md"):
        raise ValueError("仅支持 .md 文件")
    return name


def _resolve_memory_path(*, user_id: str, file_name: str) -> Path:
    """把文件名解析为 data/user/<user_id>/memory/ 下绝对路径，并阻止路径穿越。"""
    valid_name = _validate_file_name(file_name)
    user_dir = _user_memory_dir(user_id)
    base = user_dir.resolve()
    target = (user_dir / valid_name).resolve()
    if base not in target.parents and target != base:
        raise ValueError("记忆文件路径非法")
    return target


def _write_initial_memory_files(*, user_id: str, overwrite: bool) -> list[str]:
    """将代码内置初始内容写入用户记忆目录。"""
    user_dir = _ensure_user_scaffold(user_id)
    written: list[str] = []
    for file_name, initial_content in INITIAL_MEMORY_FILES.items():
        target = user_dir / file_name
        if target.exists() and not overwrite:
            continue
        target.write_text(initial_content, encoding="utf-8")
        written.append(file_name)
    return written


def _clear_memory_dir(*, user_id: str) -> None:
    """清空用户记忆目录。"""
    user_dir = _ensure_user_scaffold(user_id)
    if not user_dir.exists():
        return
    for item in user_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


async def ensure_memory_files_exist(user_id: str) -> None:
    """
    启动初始化：
    1. 保证 data/user/<user_id>/{memory,brand_library,skill_library} 目录存在。
    2. 为缺失的记忆文件写入内置初始内容。
    """
    _ensure_user_scaffold(user_id)
    _write_initial_memory_files(user_id=user_id, overwrite=False)


async def reset_memory_to_initial_content(user_id: str) -> list[str]:
    """重置用户记忆区：清空目录后使用内置初始内容全量覆盖。"""
    _ensure_user_scaffold(user_id)
    _clear_memory_dir(user_id=user_id)
    return _write_initial_memory_files(user_id=user_id, overwrite=True)


def _sort_memory_file_names(existing: list[str]) -> list[str]:
    """
    记忆文件排序策略：
    1) 先按 PREFERRED_FILE_ORDER 输出系统内置文件。
    2) 其余文件按字母序追加。
    """
    existing_set = set(existing)
    ordered = [name for name in PREFERRED_FILE_ORDER if name in existing_set]
    ordered.extend(name for name in existing if name not in ordered)
    return ordered


def list_memory_file_names(user_id: str) -> list[str]:
    """列出指定用户目录下可管理的 .md 文件名。"""
    user_dir = _ensure_user_scaffold(user_id)
    existing = sorted(
        [p.name for p in user_dir.glob("*.md") if p.is_file()],
        key=lambda x: x.lower(),
    )
    return _sort_memory_file_names(existing)


async def read_memory_file_impl(*, user_id: str, file_name: str) -> str:
    """读取指定用户的记忆文件内容。"""
    _ensure_user_scaffold(user_id)
    path = _resolve_memory_path(user_id=user_id, file_name=file_name)
    if not path.exists():
        raise FileNotFoundError(f"记忆文件不存在：{file_name}")
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        return await f.read()


async def write_memory_file_impl(
    *,
    user_id: str,
    file_name: str,
    content: str,
    mode: WriteMode = "append",
    allow_system_prompt: bool = False,
) -> str:
    """写入指定用户记忆文件，支持 append/overwrite 两种模式。"""
    _ensure_user_scaffold(user_id)
    path = _resolve_memory_path(user_id=user_id, file_name=file_name)
    if file_name == SYSTEM_PROMPT_FILE and not allow_system_prompt:
        raise PermissionError(f"{SYSTEM_PROMPT_FILE} 仅允许通过人工接口更新")
    if mode not in {"append", "overwrite"}:
        raise ValueError("mode 只能是 'append' 或 'overwrite'")
    if not isinstance(content, str):
        raise ValueError("content 必须是字符串")

    path.parent.mkdir(parents=True, exist_ok=True)
    file_mode = "a" if mode == "append" else "w"
    async with aiofiles.open(path, file_mode, encoding="utf-8") as f:
        await f.write(content)
        if mode == "append" and content and not content.endswith("\n"):
            await f.write("\n")
    return f"写入成功：{file_name}（模式：{mode}）"


async def get_current_time_impl() -> str:
    """返回当前系统时间信息（UTC 与本地）JSON 字符串。"""
    now_utc = datetime.now(dt_timezone.utc)
    now_local = now_utc.astimezone()
    payload: dict[str, Any] = {
        "utc_time": now_utc.isoformat(),
        "local_time": now_local.isoformat(),
        "local_timezone": str(now_local.tzinfo),
        "unix_timestamp": int(now_utc.timestamp()),
    }
    return json.dumps(payload, ensure_ascii=False)


def _string_arg(arguments: dict[str, Any], key: str, default: str = "") -> str:
    """读取参数字典中的字符串值；不存在时返回默认值并转 str。"""
    return str(arguments.get(key, default))


def _mode_arg(arguments: dict[str, Any], key: str = "mode", default: WriteMode = "append") -> WriteMode:
    """读取并校验写入模式，返回字面量类型以满足静态类型检查。"""
    mode = _string_arg(arguments, key, default)
    if mode not in {"append", "overwrite"}:
        raise ValueError("mode 只能是 'append' 或 'overwrite'")
    return cast(WriteMode, mode)


async def execute_tool_call(tool_name: str, arguments: dict[str, Any], *, user_id: str) -> str:
    """分发工具调用并返回字符串结果。"""
    normalized_tool_name = str(tool_name).strip()

    if normalized_tool_name == "read_memory_file":
        return await read_memory_file_impl(
            user_id=user_id,
            file_name=_string_arg(arguments, "file_name"),
        )

    if normalized_tool_name == "write_memory_file":
        return await write_memory_file_impl(
            user_id=user_id,
            file_name=_string_arg(arguments, "file_name"),
            content=_string_arg(arguments, "content"),
            mode=_mode_arg(arguments, "mode", "append"),
        )

    if normalized_tool_name == "get_current_time":
        # arguments 形参保留用于统一工具分发签名；当前工具不读取参数。
        return await get_current_time_impl()

    raise ValueError(f"未知工具：{normalized_tool_name}")


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    """把工具参数解析为 dict；支持 dict 或 JSON 字符串输入。"""
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        stripped = raw_arguments.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"工具参数 JSON 解析失败：{exc}") from exc
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("工具参数 JSON 必须是对象")
    raise ValueError("工具参数必须是字典或 JSON 字符串")
