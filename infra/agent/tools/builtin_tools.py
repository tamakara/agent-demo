"""内置工具执行器实现。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from app.errors import NotFoundError, ValidationError
from app.interfaces import IClock, IMemoryRepository, ITokenCounter, IToolRunner
from app.memory_specs import (
    COMPRESSED_MEMORY_DIR,
    COMPRESSED_MEMORY_FILE,
    DEFAULT_MEMORY_CAPACITY_RATIO,
    DEFAULT_NOTEBOOK_CAPACITY_RATIO,
    memory_file_token_limit,
    notebook_total_token_limit,
)
from domain.models import LLMConfig
from infra.agent.tools.image_tool import ImageToolService


class BuiltinToolRunner(IToolRunner):
    """工具执行器，屏蔽工具名到实现的映射。"""

    def __init__(
        self,
        memory_repo: IMemoryRepository,
        clock: IClock,
        token_counter: ITokenCounter,
        image_tool: ImageToolService | None = None,
    ) -> None:
        """注入记忆文件仓储和时钟服务。"""
        self.memory_repo = memory_repo
        self.clock = clock
        self.token_counter = token_counter
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
    ) -> None:
        """校验记忆文件访问权限。"""
        normalized_name = str(file_name or "").strip()
        if normalized_name == COMPRESSED_MEMORY_FILE and not allow_hidden_memory_files:
            raise ValidationError("当前场景不允许读取或写入压缩记忆文件")

    @staticmethod
    def _assert_no_hidden_memory_path(data_path: str) -> None:
        """屏蔽任何 ``.memory`` 路径访问。"""
        path_parts = [part for part in str(data_path or "").strip().replace("\\", "/").split("/") if part]
        if ".memory" in path_parts:
            raise ValidationError("数字员工不可访问 .memory 目录文件")

    @staticmethod
    def _total_token_limit(llm_config: LLMConfig | None) -> int:
        """返回当前总 token 限制。"""
        total_limit = int(getattr(llm_config, "total_token_limit", 200000) or 200000)
        return max(1, total_limit)

    @staticmethod
    def _tokenizer_model(llm_config: LLMConfig | None) -> str:
        return str(getattr(llm_config, "tokenizer_model", "kimi-k2.5") or "kimi-k2.5")

    def _memory_relative_path(self, file_name: str) -> str:
        relative = self.memory_repo.memory_relative_path(file_name)
        return str(relative or "").replace("\\", "/").strip()

    def _is_notebook_memory_file(self, file_name: str) -> bool:
        relative_path = self._memory_relative_path(file_name)
        return relative_path.startswith("notebook/")

    def _is_compressed_memory_file(self, file_name: str) -> bool:
        relative_path = self._memory_relative_path(file_name)
        return relative_path == f"{COMPRESSED_MEMORY_DIR}/{COMPRESSED_MEMORY_FILE}"

    def _dynamic_notebook_file_token_limit(
        self,
        *,
        user_id: str,
        employee_id: str,
        file_name: str,
        llm_config: LLMConfig | None,
    ) -> tuple[int, int, int]:
        total_limit = self._total_token_limit(llm_config)
        notebook_total_limit = notebook_total_token_limit(
            total_limit,
            notebook_capacity_ratio=getattr(
                llm_config,
                "notebook_capacity_ratio",
                DEFAULT_NOTEBOOK_CAPACITY_RATIO,
            ),
        )
        existing_files: set[str] = set()
        for existing_name in self.memory_repo.list_memory_file_names(user_id, employee_id):
            normalized = str(existing_name or "").strip()
            if not normalized:
                continue
            if self._is_notebook_memory_file(normalized):
                existing_files.add(normalized)
        existing_files.add(file_name)
        notebook_file_count = max(1, len(existing_files))
        per_file_limit = max(1, int(notebook_total_limit / notebook_file_count))
        return per_file_limit, notebook_total_limit, notebook_file_count

    async def _assert_memory_file_token_limit(
        self,
        *,
        user_id: str,
        employee_id: str,
        file_name: str,
        content: str,
        mode: str,
        llm_config: LLMConfig | None,
    ) -> None:
        """校验写入后的记忆文件大小是否超限。"""
        normalized_name = str(file_name or "").strip()
        if not normalized_name:
            return
        tokenizer_model = self._tokenizer_model(llm_config)
        token_count = self.token_counter.count_tokens(content, tokenizer_model)
        action = "追加" if mode == "append" else "覆盖"

        if self._is_compressed_memory_file(normalized_name):
            token_limit = memory_file_token_limit(
                normalized_name,
                self._total_token_limit(llm_config),
                memory_capacity_ratio=getattr(llm_config, "memory_capacity_ratio", DEFAULT_MEMORY_CAPACITY_RATIO),
            )
            if token_limit is None or token_count <= token_limit:
                return
            total_limit = self._total_token_limit(llm_config)
            ratio_pct = max(1, int((token_limit * 100) / max(1, total_limit)))
            raise ValidationError(
                f"{action}写入失败：{normalized_name} 超过大小限制。"
                f"当前 {token_count} token，限制 {token_limit} token（total_token_limit 的 {ratio_pct}%）。"
                "请读取原内容并压缩该记忆文件，再使用 mode='overwrite' 整体写回。"
            )

        if not self._is_notebook_memory_file(normalized_name):
            return

        per_file_limit, notebook_total_limit, notebook_file_count = self._dynamic_notebook_file_token_limit(
            user_id=user_id,
            employee_id=employee_id,
            file_name=normalized_name,
            llm_config=llm_config,
        )
        if token_count <= per_file_limit:
            return
        raise ValidationError(
            f"{action}写入失败：{normalized_name} 超过 notebook 文件容量限制。"
            f"当前 {token_count} token，单文件限制 {per_file_limit} token；"
            f"notebook 总预算 {notebook_total_limit} token，当前分摊文件数 {notebook_file_count}。"
            "请减少内容后重试，或先读取原内容压缩后使用 mode='overwrite' 整体写回。"
        )

    async def _content_after_write(
        self,
        *,
        user_id: str,
        employee_id: str,
        file_name: str,
        content: str,
        mode: str,
    ) -> str:
        """根据写入模式计算写入后的完整文件内容。"""
        normalized_content = str(content or "")
        if mode == "overwrite":
            return normalized_content

        try:
            existing_content = await self.memory_repo.read_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=file_name,
            )
        except NotFoundError:
            existing_content = ""

        appended = normalized_content
        if appended and not appended.endswith("\n"):
            appended = f"{appended}\n"
        return f"{existing_content}{appended}"

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
            )
            return await self.memory_repo.read_memory_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=file_name,
            )

        if normalized_tool_name == "write_notebook_file":
            file_name = self._string_arg(arguments, "file_name")
            mode = self._mode_arg(arguments, "mode", "append")
            normalized_name = str(file_name or "").strip()
            self._assert_memory_file_access(
                file_name,
                allow_hidden_memory_files=allow_hidden_memory_files,
            )
            content = self._string_arg(arguments, "content")
            resulting_content = content
            if normalized_name:
                resulting_content = await self._content_after_write(
                    user_id=user_id,
                    employee_id=employee_id,
                    file_name=normalized_name,
                    content=content,
                    mode=mode,
                )
            await self._assert_memory_file_token_limit(
                user_id=user_id,
                employee_id=employee_id,
                file_name=normalized_name,
                content=resulting_content,
                mode=mode,
                llm_config=llm_config,
            )
            return await self.memory_repo.write_notebook_file(
                user_id=user_id,
                employee_id=employee_id,
                file_name=file_name,
                content=content,
                mode=mode,
            )

        if normalized_tool_name == "get_current_time":
            return await self.clock.get_current_time()

        if normalized_tool_name == "read_visible_file_by_path":
            data_path = self._string_arg(arguments, "path")
            self._assert_no_hidden_memory_path(data_path)
            abs_path = self.memory_repo.resolve_data_file_path(
                user_id=user_id,
                employee_id=employee_id,
                data_path=data_path,
                access_mode="read",
            )
            file_path = Path(abs_path)
            if file_path.suffix.lower() not in {".md", ".txt"}:
                raise ValidationError(f"仅支持读取文本文件（.md/.txt）：{data_path}")
            try:
                return file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(f"文本文件编码不支持 UTF-8：{data_path}") from exc

        if normalized_tool_name == "list_employee_visible_directory":
            directory_path = self._string_arg(arguments, "path")
            if not directory_path.strip():
                raise ValidationError("path 不能为空；查看素材库请使用 path='brand_library'")
            result = self.memory_repo.list_employee_visible_directory(
                user_id=user_id,
                employee_id=employee_id,
                data_path=directory_path,
            )
            return json.dumps(result, ensure_ascii=False)

        if normalized_tool_name == "copy_library_file_to_workspace":
            result = self.memory_repo.copy_library_file_to_workspace(
                user_id=user_id,
                employee_id=employee_id,
                source_path=self._string_arg(arguments, "source_path"),
                workspace_file_name=self._string_arg(arguments, "workspace_file_name", ""),
            )
            return json.dumps(result, ensure_ascii=False)

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
            raise ValidationError(
                "brand_library 对数字员工为只读目录，不允许写入。"
                "如需编辑库文件，请先调用 copy_library_file_to_workspace 复制到 workspace。"
            )

        raise ValidationError(f"未知工具：{normalized_tool_name}")
