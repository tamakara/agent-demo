"""工具 Schema 提供器。"""

from __future__ import annotations

from typing import Any

from app.ports.repositories import ToolSchemaProviderPort
from infra.tools.tool_registry import TOOL_SCHEMAS


class ToolSchemaProvider(ToolSchemaProviderPort):
    """返回当前内置工具 Schema 列表。"""

    def list_tool_schemas(self) -> list[dict[str, Any]]:
        """返回工具 Schema 的浅拷贝，避免上层意外改写全局常量。"""
        return [dict(item) for item in TOOL_SCHEMAS]
