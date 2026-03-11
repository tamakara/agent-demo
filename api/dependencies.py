"""API 层依赖装配与应用容器构建。"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.memory_file_service import MemoryFileService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.use_cases.chat_stream_use_case import ChatStreamUseCase
from app.use_cases.flush_use_case import FlushUseCase
from app.use_cases.memory_context import MemoryContextService
from app.use_cases.memory_status_use_case import MemoryStatusUseCase
from infra.llm.openai_gateway import OpenAIGateway
from infra.llm.tiktoken_counter import TiktokenCounter
from infra.memory.file_repository import FileMemoryRepository
from infra.sqlite.repository import SQLiteRepository
from infra.tools.builtin_tools import BuiltinToolRunner
from infra.tools.clock import SystemClock


@dataclass(slots=True)
class AppContainer:
    """应用启动后共享的依赖容器。"""
    sqlite_repo: SQLiteRepository
    memory_file_repo: FileMemoryRepository
    chat_stream_use_case: ChatStreamUseCase
    flush_use_case: FlushUseCase
    memory_status_use_case: MemoryStatusUseCase
    session_service: SessionService
    settings_service: SettingsService
    memory_file_service: MemoryFileService


async def build_container() -> AppContainer:
    """构建并初始化 API 层运行所需的全部依赖。"""
    # 先初始化持久化层，避免上层服务在首次请求时触发冷启动开销。
    sqlite_repo = SQLiteRepository()
    await sqlite_repo.initialize()

    # 组装工具链和 LLM 网关。
    memory_file_repo = FileMemoryRepository()
    clock = SystemClock()
    tool_runner = BuiltinToolRunner(memory_repo=memory_file_repo, clock=clock)
    llm_gateway = OpenAIGateway(tool_runner=tool_runner)
    token_counter = TiktokenCounter()

    # 记忆上下文服务聚合核心读写策略，供多个用例复用。
    memory_context = MemoryContextService(
        session_repo=sqlite_repo,
        message_repo=sqlite_repo,
        settings_repo=sqlite_repo,
        memory_repo=memory_file_repo,
        llm_gateway=llm_gateway,
        token_counter=token_counter,
    )

    # 组装应用层用例与外部服务门面。
    chat_stream_use_case = ChatStreamUseCase(memory_context)
    flush_use_case = FlushUseCase(memory_context)
    memory_status_use_case = MemoryStatusUseCase(memory_context)

    session_service = SessionService(session_repo=sqlite_repo, message_repo=sqlite_repo)
    settings_service = SettingsService(settings_repo=sqlite_repo)
    memory_file_service = MemoryFileService(memory_repo=memory_file_repo)

    return AppContainer(
        sqlite_repo=sqlite_repo,
        memory_file_repo=memory_file_repo,
        chat_stream_use_case=chat_stream_use_case,
        flush_use_case=flush_use_case,
        memory_status_use_case=memory_status_use_case,
        session_service=session_service,
        settings_service=settings_service,
        memory_file_service=memory_file_service,
    )

