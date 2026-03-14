"""工具注册表与参数解析工具。"""

from __future__ import annotations

import json
from typing import Any


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_memory_file",
            "description": "读取当前数字员工隔离目录中的 Markdown 记忆文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：memory.md 或 人格设定.md",
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
            "description": "向当前数字员工隔离目录中的记忆文件写入文本，支持追加或覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "目标记忆文件名，例如：memory.md 或 人格设定.md",
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
    {
        "type": "function",
        "function": {
            "name": "image_gen_edit",
            "description": (
                "使用 seedream-4-5 执行文生图，"
                "图片会保存到当前数字员工的 /employee/{employee_id}/workspace 目录。"
                "若需要进入用户素材库，请继续调用 copy_workspace_image_to_brand_library。"
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
    {
        "type": "function",
        "function": {
            "name": "copy_workspace_image_to_brand_library",
            "description": "将 /employee/{employee_id}/workspace 下的图片复制到用户 /brand_library 目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_file_name": {
                        "type": "string",
                        "description": "workspace 中要复制的图片文件名。",
                    },
                    "brand_file_name": {
                        "type": "string",
                        "description": "brand_library 目标文件名，可选，不传则沿用源文件名。",
                    },
                },
                "required": ["workspace_file_name"],
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
