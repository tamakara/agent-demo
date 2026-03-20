"""工具注册表与参数解析工具。"""

from __future__ import annotations

import json
from typing import Any


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_memory_file",
            "description": "读取当前数字员工目录中的 Markdown 记忆文件（含 notebook/*.md 与 .memory/memory.md）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：memory.md、file.md、soul.md、schedule.md、workbook.md",
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
            "name": "write_notebook_file",
            "description": (
                "向当前数字员工记忆文件写入文本。"
                "受管记忆文件（memory.md/file.md/soul.md/schedule.md/workbook.md）"
                "默认可 append 或 overwrite；"
                "memory.md 按 memory_capacity_ratio 限制，notebook/*.md 按 notebook_capacity_ratio 动态平分限制；"
                "若写入后超过限制会报错，"
                "需压缩后用 overwrite 整体写回。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：memory.md、file.md、soul.md、schedule.md、workbook.md",
                    },
                    "content": {
                        "type": "string",
                        "description": "待写入的文本内容。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["append", "overwrite"],
                        "description": (
                            "append 表示追加写入，overwrite 表示覆盖写入。"
                            "受管记忆文件超限时应压缩并改用 overwrite。"
                        ),
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
            "name": "read_visible_file_by_path",
            "description": (
                "按用户数据根相对路径读取可见文本文件内容（支持 brand_library、skill_library、employee/*）。"
                "可读取其他员工目录文件，但 .memory 目录不可访问。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "文件相对路径，例如 "
                            "employee/2/workspace/notes.md 或 brand_library/brief.txt。"
                        ),
                    }
                },
                "required": ["path"],
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
    {
        "type": "function",
        "function": {
            "name": "list_employee_visible_directory",
            "description": (
                "按当前数字员工权限列出目录内容。"
                "根目录 path='/' 可查看 brand_library、employee、skill_library。"
                "employee 下可查看所有员工目录，但只有当前员工目录 can_write=true。"
                "所有 .memory 目录都会被隐藏。"
                "brand_library 与 skill_library 对数字员工均为只读（can_write=false）。"
                "素材库即 brand_library；当用户说“素材库”时应传 path='brand_library'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "要查看的目录路径。示例：'brand_library'、'employee/2/workspace'、'/'。",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_library_file_to_workspace",
            "description": (
                "将 brand_library 或 skill_library 中的文件复制到当前数字员工 workspace，"
                "用于在 workspace 内继续编辑。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "源文件路径，仅支持 brand_library/... 或 skill_library/...",
                    },
                    "workspace_file_name": {
                        "type": "string",
                        "description": "目标文件名（可选，不传则沿用源文件名；重名时自动去重）。",
                    },
                },
                "required": ["source_path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "image_gen_edit",
            "description": (
                "使用 seedream-4-5 执行文生图，"
                "图片会保存到当前数字员工的 employee/{employee_id}/workspace 目录。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nameHint": {
                        "type": "string",
                        "description": "输出文件名提示词（必填），用于生成 workspace 文件名。",
                    },
                    "imagePath": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参考图路径数组，可空。",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "图片生成提示词（文生图）。",
                    },
                    "aspectRatio": {
                        "type": "string",
                        "description": "比例，例如 auto、1:1、16:9。",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["2K", "4K"],
                        "description": "分辨率档位，支持 2K / 4K。",
                    },
                },
                "required": ["nameHint", "prompt"],
                "additionalProperties": False,
            },
        },
    },
]


def parse_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    """将工具参数解析为字典对象。"""
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


def _required_fields_from_parameters(parameters: dict[str, Any]) -> list[str]:
    """从工具参数定义中提取必填字段名。"""
    raw_required = parameters.get("required", [])
    if not isinstance(raw_required, list):
        return []
    return [str(field).strip() for field in raw_required if str(field).strip()]


def _field_type(parameters: dict[str, Any], field_name: str) -> str:
    """读取字段 schema 的 type。"""
    properties = parameters.get("properties", {})
    if not isinstance(properties, dict):
        return ""
    field_schema = properties.get(field_name, {})
    if not isinstance(field_schema, dict):
        return ""
    return str(field_schema.get("type", "")).strip().lower()


def find_missing_required_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
) -> list[str]:
    """
    根据注册表 schema 校验工具必填参数是否齐全。

    规则：
    - required 字段不存在，判定缺失；
    - required 字段值为 ``None``，判定缺失；
    - required 且类型为 ``string``，空白字符串判定缺失。
    """
    normalized_tool_name = str(tool_name or "").strip()
    if not normalized_tool_name:
        return []

    target_schema: dict[str, Any] | None = None
    for schema in TOOL_SCHEMAS:
        function_spec = schema.get("function", {})
        if not isinstance(function_spec, dict):
            continue
        if str(function_spec.get("name", "")).strip() == normalized_tool_name:
            target_schema = function_spec
            break
    if target_schema is None:
        return []

    parameters = target_schema.get("parameters", {})
    if not isinstance(parameters, dict):
        return []

    missing_fields: list[str] = []
    for field_name in _required_fields_from_parameters(parameters):
        if field_name not in arguments:
            missing_fields.append(field_name)
            continue
        value = arguments.get(field_name)
        if value is None:
            missing_fields.append(field_name)
            continue
        if _field_type(parameters, field_name) == "string" and not str(value).strip():
            missing_fields.append(field_name)

    return missing_fields
