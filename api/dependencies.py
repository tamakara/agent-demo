"""API 层依赖装配模块。

该模块是“依赖注入唯一组装点”：
- 在这里实例化 infra 层具体实现。
- 在这里把实现注入到 app 层服务。
- 路由和服务都不直接 new 基建对象。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.agent_service import AgentService
from app.services.employee_service import EmployeeService
from app.services.settings_service import SettingsService
from app.services.storage_service import StorageService
from infra.agent.kimi_tokenizer_counter import KimiTokenizerCounter
from infra.agent.langgraph_agent_engine import LangGraphAgentEngine
from infra.agent.template_repository import FilePromptTemplateRepository
from infra.agent.tools.builtin_tools import BuiltinToolRunner
from infra.agent.tools.clock import SystemClock
from infra.agent.tools.schema_provider import ToolSchemaProvider
from infra.memory.file_repository import FileMemoryRepository
from infra.sqlite.repository import SQLiteRepository


@dataclass(slots=True)
class AppContainer:
    """应用运行时共享容器。

    只暴露 API 层真正需要使用的服务与资源。
    """

    sqlite_repo: SQLiteRepository
    agent_service: AgentService
    employee_service: EmployeeService
    settings_service: SettingsService
    storage_service: StorageService


async def build_container() -> AppContainer:
    """构建并初始化完整依赖图。"""
    # 1) 先初始化持久化层，确保后续服务调用不会触发冷启动。
    sqlite_repo = SQLiteRepository()
    await sqlite_repo.initialize()
    # SQLiteRepository 同时承载 session/message/settings 三类仓储接口实现。

    # 2) 组装通用基础能力：文件仓储、token 计数、时钟、工具执行器。
    memory_repo = FileMemoryRepository()
    token_counter = KimiTokenizerCounter()
    clock = SystemClock()
    tool_runner = BuiltinToolRunner(
        memory_repo=memory_repo,
        clock=clock,
        token_counter=token_counter,
    )

    # 3) 组装模型能力与提示词仓储。
    tool_schema_provider = ToolSchemaProvider()
    agent_engine = LangGraphAgentEngine(tool_runner=tool_runner)
    prompt_templates = FilePromptTemplateRepository()
    # Prompt 模板仓储和 Agent 引擎都以接口形式注入，便于后续替换实现。

    # 4) 组装应用核心服务（业务只依赖接口，不依赖具体实现细节）。
    agent_service = AgentService(
        session_repo=sqlite_repo,
        message_repo=sqlite_repo,
        settings_repo=sqlite_repo,
        memory_repo=memory_repo,
        agent_engine=agent_engine,
        token_counter=token_counter,
        prompt_templates=prompt_templates,
        tool_schema_provider=tool_schema_provider,
    )
    employee_service = EmployeeService(session_repo=sqlite_repo, message_repo=sqlite_repo)
    settings_service = SettingsService(settings_repo=sqlite_repo)
    storage_service = StorageService(memory_repo=memory_repo)
    # storage_service 复用同一 memory_repo，保证 API 文件读写与工具写入语义一致。

    return AppContainer(
        sqlite_repo=sqlite_repo,
        agent_service=agent_service,
        employee_service=employee_service,
        settings_service=settings_service,
        storage_service=storage_service,
    )
