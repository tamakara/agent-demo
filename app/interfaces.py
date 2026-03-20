"""应用层抽象契约（依赖倒置核心）。

约束：
- app 层只依赖本文件定义的抽象接口，不依赖 infra 具体实现。
- infra 层必须实现这些接口后再注入到 app 服务中。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Sequence
from typing import Any, Callable

from domain.models import GlobalSettings, LLMConfig, LLMRunResult


# 事件回调：用于把工具事件/模型事件向 API SSE 层透传。
EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
# system 刷新器：工具写入记忆后可即时刷新 system prompt。
SystemMessageRefresher = Callable[[], Awaitable[str] | str]


class ISessionRepository(ABC):
    """会话仓储接口。"""
    @abstractmethod
    async def ensure_session(self, user_id: str, session_id: str) -> None:
        ...

    @abstractmethod
    async def create_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        ...

    @abstractmethod
    async def list_sessions(self, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def delete_session(self, user_id: str, session_id: str) -> None:
        ...

    @abstractmethod
    async def set_is_compressing(self, user_id: str, session_id: str, value: bool) -> None:
        ...

    @abstractmethod
    async def update_workbench_summary(self, user_id: str, session_id: str, summary: str) -> None:
        ...


class IMessageRepository(ABC):
    """消息仓储接口。"""
    @abstractmethod
    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        message_kind: str,
        content: str,
        zone: str,
        token_count: int,
    ) -> int:
        ...

    @abstractmethod
    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        zones: Sequence[str] | None = None,
        roles: Sequence[str] | None = None,
        message_kinds: Sequence[str] | None = None,
        ascending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def sum_tokens_by_zone(self, user_id: str, session_id: str) -> dict[str, int]:
        ...

    @abstractmethod
    async def clear_messages(self, user_id: str, session_id: str) -> None:
        ...


class ISettingsRepository(ABC):
    """用户设置仓储接口。"""
    @abstractmethod
    async def get_global_settings(self, user_id: str) -> GlobalSettings:
        ...

    @abstractmethod
    async def update_global_settings(self, settings: GlobalSettings) -> GlobalSettings:
        ...


class IMemoryRepository(ABC):
    """记忆文件与目录仓储接口。"""
    @abstractmethod
    async def ensure_memory_files_exist(self, user_id: str, employee_id: str) -> None:
        ...

    @abstractmethod
    async def reset_memory_to_initial_content(self, user_id: str, employee_id: str) -> list[str]:
        ...

    @abstractmethod
    async def delete_employee_data(self, user_id: str, employee_id: str) -> None:
        ...

    @abstractmethod
    def list_memory_file_names(self, user_id: str, employee_id: str) -> list[str]:
        ...

    @abstractmethod
    def list_employee_data_paths(self, user_id: str, employee_id: str = "1") -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def employee_data_root(self, user_id: str, employee_id: str = "1") -> str:
        ...

    @abstractmethod
    def memory_relative_path(self, file_name: str) -> str:
        ...

    @abstractmethod
    def resolve_data_file_path(
        self,
        user_id: str,
        data_path: str,
        *,
        employee_id: str = "1",
        access_mode: str = "read",
        access_scope: str = "employee",
    ) -> str:
        ...

    @abstractmethod
    def list_employee_visible_directory(
        self,
        user_id: str,
        employee_id: str,
        data_path: str = "/",
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def copy_library_file_to_workspace(
        self,
        user_id: str,
        employee_id: str,
        source_path: str,
        *,
        workspace_file_name: str = "",
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    async def read_memory_file(self, *, user_id: str, employee_id: str, file_name: str) -> str:
        ...

    @abstractmethod
    async def write_notebook_file(
        self,
        *,
        user_id: str,
        employee_id: str,
        file_name: str,
        content: str,
        mode: str,
    ) -> str:
        ...


class IAgentEngine(ABC):
    """Agent 引擎接口（支持工具循环与图执行）。"""
    @abstractmethod
    async def process(
        self,
        *,
        user_id: str,
        employee_id: str,
        session_id: str,
        messages: list[dict[str, Any]],
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
        refresh_system_message: SystemMessageRefresher | None = None,
        allow_hidden_memory_files: bool = False,
    ) -> LLMRunResult:
        ...


class ITokenCounter(ABC):
    """Token 计数与截断接口。"""
    @abstractmethod
    def count_tokens(self, text: str, model: str) -> int:
        ...

    @abstractmethod
    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:
        ...


class IToolRunner(ABC):
    """工具执行器接口。"""
    @abstractmethod
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
        ...


class IToolSchemaProvider(ABC):
    """工具 schema 提供接口。"""
    @abstractmethod
    def list_tool_schemas(self) -> list[dict[str, Any]]:
        ...


class IClock(ABC):
    """时钟服务接口。"""
    @abstractmethod
    async def get_current_time(self) -> str:
        ...


class IPromptTemplateRepository(ABC):
    """提示词模板仓储接口。"""
    @abstractmethod
    def compose_chat_system_prompt(
        self,
        *,
        tool_definitions: str,
        memory_core: str,
        memory_file: str,
        memory_persona: str,
        memory_schedule: str,
        memory_workbook: str,
        workbench_summary: str,
    ) -> str:
        ...

    @abstractmethod
    def compose_tool_definitions(self, *, tool_names: list[str]) -> str:
        ...

    @abstractmethod
    def compose_compression_system_prompt(
        self,
        *,
        tool_definitions: str,
        memory_file_path: str,
        memory_token_limit: int,
    ) -> str:
        ...

    @abstractmethod
    def compose_image_generation_prompt(self, *, user_prompt: str) -> str:
        ...
