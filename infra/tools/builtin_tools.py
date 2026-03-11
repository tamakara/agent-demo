"""内置工具执行器实现。"""

from __future__ import annotations

from typing import Any, cast

from app.ports.repositories import ClockPort, MemoryFileRepositoryPort
from common.errors import ValidationError


class BuiltinToolRunner:
    """工具执行器，屏蔽工具名到实现的映射。"""

    def __init__(self, memory_repo: MemoryFileRepositoryPort, clock: ClockPort) -> None:
        """注入记忆文件仓储和时钟服务。"""
        self.memory_repo = memory_repo
        self.clock = clock

    @staticmethod
    def _string_arg(arguments: dict[str, Any], key: str, default: str = "") -> str:
        """按键读取字符串参数。"""
        return str(arguments.get(key, default))

    @classmethod
    def _mode_arg(cls, arguments: dict[str, Any], key: str = "mode", default: str = "append") -> str:
        """读取并校验写入模式参数。"""
        mode = cls._string_arg(arguments, key, default)
        if mode not in {"append", "overwrite"}:
            raise ValidationError("mode 只能是 'append' 或 'overwrite'")
        return cast(str, mode)

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        user_id: str,
        employee_id: str,
    ) -> str:
        """根据工具名分发执行内置工具。"""
        normalized_tool_name = str(tool_name).strip()

        if normalized_tool_name == "read_memory_file":
            return await self.memory_repo.read_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=self._string_arg(arguments, "file_name"),
            )

        if normalized_tool_name == "write_memory_file":
            return await self.memory_repo.write_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=self._string_arg(arguments, "file_name"),
                content=self._string_arg(arguments, "content"),
                mode=self._mode_arg(arguments, "mode", "append"),
            )

        if normalized_tool_name == "get_current_time":
            return await self.clock.get_current_time()

        raise ValidationError(f"未知工具：{normalized_tool_name}")
