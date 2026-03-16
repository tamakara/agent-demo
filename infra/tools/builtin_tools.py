"""内置工具执行器实现。"""

from __future__ import annotations

import json
from typing import Any, cast

from app.ports.repositories import ClockPort, MemoryFileRepositoryPort
from common.errors import ValidationError
from domain.chat.memory_files import COMPRESSED_MEMORY_FILE
from domain.models import LLMConfig
from infra.tools.image_tool import ImageToolService


class BuiltinToolRunner:
    """工具执行器，屏蔽工具名到实现的映射。"""

    def __init__(
        self,
        memory_repo: MemoryFileRepositoryPort,
        clock: ClockPort,
        image_tool: ImageToolService | None = None,
    ) -> None:
        """注入记忆文件仓储和时钟服务。"""
        self.memory_repo = memory_repo
        self.clock = clock
        self.image_tool = image_tool or ImageToolService()

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

    @staticmethod
    def _assert_memory_file_access(
        file_name: str,
        *,
        allow_hidden_memory_files: bool,
        is_write: bool,
        mode: str = "",
    ) -> None:
        """校验记忆文件访问权限，默认禁止点开头隐藏文件。"""
        normalized_name = str(file_name or "").strip()
        if not normalized_name.startswith("."):
            return
        if normalized_name != COMPRESSED_MEMORY_FILE:
            raise ValidationError("隐藏记忆文件不可访问")
        if not allow_hidden_memory_files:
            raise ValidationError("当前场景不允许读取或写入隐藏记忆文件")
        if is_write and mode != "overwrite":
            raise ValidationError("隐藏记忆文件仅支持覆盖写入")

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        user_id: str,
        employee_id: str,
        llm_config: LLMConfig | None = None,
        allow_hidden_memory_files: bool = False,
    ) -> str:
        """根据工具名分发执行内置工具。"""
        normalized_tool_name = str(tool_name).strip()

        if normalized_tool_name == "read_memory_file":
            file_name = self._string_arg(arguments, "file_name")
            self._assert_memory_file_access(
                file_name,
                allow_hidden_memory_files=allow_hidden_memory_files,
                is_write=False,
            )
            return await self.memory_repo.read_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=file_name,
            )

        if normalized_tool_name == "write_memory_file":
            file_name = self._string_arg(arguments, "file_name")
            mode = self._mode_arg(arguments, "mode", "append")
            self._assert_memory_file_access(
                file_name,
                allow_hidden_memory_files=allow_hidden_memory_files,
                is_write=True,
                mode=mode,
            )
            return await self.memory_repo.write_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=file_name,
                content=self._string_arg(arguments, "content"),
                mode=mode,
            )

        if normalized_tool_name == "get_current_time":
            return await self.clock.get_current_time()

        if normalized_tool_name == "image_gen_edit":
            await self.memory_repo.ensure_memory_files_exist(user_id, employee_id)
            tool_result = await self.image_tool.generate_image_to_workspace(
                user_id=user_id,
                employee_id=employee_id,
                llm_config=llm_config,
                name_hint=self._string_arg(arguments, "nameHint"),
                image_paths=arguments.get("imagePath"),
                prompt=self._string_arg(arguments, "prompt"),
                aspect_ratio=self._string_arg(arguments, "aspectRatio", ""),
                resolution=self._string_arg(arguments, "resolution", ""),
            )
            return json.dumps(tool_result, ensure_ascii=False)

        if normalized_tool_name == "copy_workspace_image_to_brand_library":
            await self.memory_repo.ensure_memory_files_exist(user_id, employee_id)
            tool_result = self.image_tool.copy_workspace_image_to_brand_library(
                user_id=user_id,
                employee_id=employee_id,
                workspace_file_name=self._string_arg(arguments, "workspace_file_name"),
                brand_file_name=self._string_arg(arguments, "brand_file_name", ""),
            )
            return json.dumps(tool_result, ensure_ascii=False)

        raise ValidationError(f"未知工具：{normalized_tool_name}")
