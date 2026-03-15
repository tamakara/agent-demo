# 分层与依赖规则

## 本文范围

本文仅覆盖：

- 分层依赖方向
- 端口接口定义边界
- 可替换组件约束

本文不覆盖：

- 业务流程细节
- API 字段与示例

## 1. 分层依赖图

```text
api -> app -> domain
       |      ^
       v      |
      ports <- infra

common: 可被所有层复用
```

## 2. 端口接口（app/ports）

- `SessionRepositoryPort`
- `MessageRepositoryPort`
- `UserSettingsRepositoryPort`
- `MemoryFileRepositoryPort`
- `LLMGatewayPort`
- `TokenCounterPort`
- `ClockPort`
- `ToolSchemaProviderPort`

这些接口定义“应用层所需能力”，不暴露具体实现细节。

## 3. 适配器实现（infra）

- `infra/sqlite/repository.py`：实现 session/message/settings 仓储
- `infra/memory/file_repository.py`：实现记忆文件仓储
- `infra/llm/openai_gateway.py`：实现 LLM 网关
- `infra/llm/kimi_tokenizer_counter.py`：实现 Kimi K2.5 token 计数器
- `infra/tools/clock.py`：实现时钟端口
- `infra/tools/schema_provider.py`：实现工具 schema 提供器

## 4. 允许的替换方式

1. 保持端口不变，替换 `infra` 中某个实现
2. 通过 `api/dependencies.py` 完成依赖装配切换
3. 不允许在 `domain` 中直接引入第三方 SDK

## 5. 违反边界的典型反例

1. 在 `domain/*` 中直接访问 SQLite
2. 在 `api/routes.py` 中直接写 SQL
3. 在 `app/chat/use_cases/*` 中直接 new OpenAI client

上述反例都会破坏可测试性与可替换性。
