"""应用层端口协议与回调类型定义。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from domain.models import GlobalSettings, LLMConfig, LLMRunResult


EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
SystemMessageRefresher = Callable[[], Awaitable[str] | str]


class SessionRepositoryPort(Protocol):
    """会话仓储端口协议。"""

    async def ensure_session(self, user_id: str, session_id: str) -> None:
        """确保会话存在，不存在则创建。"""
        ...

    async def create_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        """创建会话并返回会话对象。"""
        ...

    async def get_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        """读取单个会话状态。"""
        ...

    async def list_sessions(self, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """按更新时间倒序列出用户会话。"""
        ...

    async def set_is_flushing(self, user_id: str, session_id: str, value: bool) -> None:
        """更新会话刷盘状态标记。"""
        ...

    async def update_workbench_summary(self, user_id: str, session_id: str, summary: str) -> None:
        """更新会话工作台摘要文本。"""
        ...


class MessageRepositoryPort(Protocol):
    """消息仓储端口协议。"""

    async def add_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        zone: str,
        token_count: int,
    ) -> int:
        """新增一条消息并返回消息 ID。"""
        ...

    async def list_messages(
        self,
        user_id: str,
        session_id: str,
        *,
        zones: Sequence[str] | None = None,
        roles: Sequence[str] | None = None,
        ascending: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按条件检索消息列表。"""
        ...

    async def sum_tokens_by_zone(self, user_id: str, session_id: str) -> dict[str, int]:
        """按 zone 汇总 token 数。"""
        ...

    async def clear_messages(self, user_id: str, session_id: str) -> None:
        """清空指定会话的全部消息。"""
        ...


class UserSettingsRepositoryPort(Protocol):
    """用户设置仓储端口协议。"""

    async def get_global_settings(self, user_id: str) -> GlobalSettings:
        """读取用户全局配置。"""
        ...

    async def update_global_settings(self, settings: GlobalSettings) -> GlobalSettings:
        """更新用户全局配置并返回最新值。"""
        ...


class MemoryFileRepositoryPort(Protocol):
    """记忆文件仓储端口协议。"""

    async def ensure_memory_files_exist(self, user_id: str) -> None:
        """确保用户的记忆文件目录与默认文件存在。"""
        ...

    async def reset_memory_to_initial_content(self, user_id: str) -> list[str]:
        """将记忆文件重置为初始内容并返回恢复文件名列表。"""
        ...

    def list_memory_file_names(self, user_id: str) -> list[str]:
        """列出用户记忆文件名。"""
        ...

    async def read_memory_file(self, *, user_id: str, file_name: str) -> str:
        """读取指定记忆文件内容。"""
        ...

    async def write_memory_file(
        self,
        *,
        user_id: str,
        file_name: str,
        content: str,
        mode: str,
        allow_system_prompt: bool = False,
    ) -> str:
        """写入指定记忆文件并返回最新内容。"""
        ...


class LLMGatewayPort(Protocol):
    """LLM 网关端口协议。"""

    async def run_with_tools(
        self,
        user_id: str,
        messages: list[dict[str, Any]],
        llm_config: LLMConfig,
        max_tool_rounds: int,
        on_event: EventCallback | None = None,
        refresh_system_message: SystemMessageRefresher | None = None,
    ) -> LLMRunResult:
        """执行 LLM 对话并在需要时处理工具调用。"""
        ...


class TokenCounterPort(Protocol):
    """Token 计数端口协议。"""

    def count_tokens(self, text: str, model: str) -> int:
        """统计文本 token 数。"""
        ...

    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:
        """将文本截断到 token 上限内。"""
        ...


class ClockPort(Protocol):
    """时间服务端口协议。"""

    async def get_current_time(self) -> str:
        """返回当前时间信息。"""
        ...
