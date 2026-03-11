"""工具注册表与参数解析工具。"""

from __future__ import annotations

import json
from typing import Any


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
