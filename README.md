# agent-demo

一个基于 **FastAPI + OpenAI 兼容接口** 的长上下文记忆模块演示项目，用于测试并可视化验证 **200K token 窗口** 下的会话记忆管理能力。

## 1. 项目亮点

- 200K 上下文窗口分区（常驻区 40K + 对话区 160K）
- 超阈值自动异步刷盘（`BackgroundTasks`）
- 原生工具调用（不依赖 LangChain）
- 内置当前时间工具（`get_current_time`），支持时间敏感问答
- 后端无 `.env`：模型配置以全局单例存储在 SQLite，并在请求时透传
- 可视化前端：配置面板、token 仪表盘、聊天区、记忆文件编辑器

## 2. 技术栈

- Python 3.12（建议）
- FastAPI
- Uvicorn
- Pydantic
- httpx（通过 OpenAI 兼容 Chat Completions 接口调用）
- tiktoken
- aiofiles
- SQLite

## 3. 目录结构

```text
agent-demo/
├── main.py
├── run.py
├── requirements.txt
├── core/
│   ├── agent.py
│   ├── db.py
│   ├── memory_manager.py
│   ├── models.py
│   └── tools.py
├── data/
│   ├── agent_state.db        # 首次启动自动创建
│   └── memory/               # 首次启动自动创建
├── static/
└── docs/
```

## 4. 快速开始

## 4.1 安装依赖

```bash
python -m pip install -r requirements.txt
```

## 4.2 启动项目

```bash
python run.py
```

启动后访问：

- 前端页面：`http://127.0.0.1`
- OpenAPI 文档：`http://127.0.0.1/docs`

首次运行时会自动初始化运行数据：

1. 创建 `data/agent_state.db`
2. 创建 `data/memory/`
3. 将 `core/tools.py` 中内置的初始记忆内容写入 `data/memory/*.md`（仅写入缺失文件）

如果需要清空全部运行数据，直接删除 `data/` 文件夹即可，下次启动会自动重新初始化。

## 4.3 前端使用步骤

1. 在对话区选择或新建 `session id`。
2. 在“LLM 配置”面板确认或修改 `model name / api key / base url / max tool rounds`（已预置默认值）。
3. 点击“保存配置”，配置会写入全局 SQLite 配置表（与 `session id` 无关）。
4. 在聊天输入框发送消息，观察工具调用日志和模型回复。
5. 在“记忆文件”区域查看并编辑各 `.md` 文件（含 `系统提示词.md`）。
6. 观察“token 仪表盘”中常驻区、对话区、缓冲区变化。
7. 如需立即归档，点击“手动刷盘”。

## 5. 核心机制

## 5.1 上下文分区

- 总容量：`200000` token
- 常驻区：系统提示词 + 记忆文件 + 工作台摘要 + 最近 6 轮
- 对话区：本轮会话与工具交互
- 缓冲区：刷盘期间的新增消息

## 5.2 异步刷盘

当总 token 数达到阈值（默认 `200000`）时，系统会：

1. 标记会话刷盘中
2. 将对话区内容交给模型归档
3. 通过工具写入长期记忆文件
4. 生成新的工作台摘要
5. 清理对话区并保留最近 6 轮

## 5.3 系统提示词文件化

- 全局底层规则存放于：`data/memory/系统提示词.md`
- 聊天流程与刷盘流程共同读取该文件
- 该文件仅允许人工接口编辑，工具调用禁止写入

## 5.4 素材库记忆占位策略

- `data/memory/素材库记忆.md` 保留为占位文件
- 默认不加载进常驻区
- 是否调用由系统提示词规则约束（默认不主动调用）

## 6. API 速览

- `POST /api/chat`：SSE 聊天接口（含工具调用事件）
- `GET /api/llm-config`：读取全局 LLM 配置
- `PUT /api/llm-config`：保存全局 LLM 配置
- `GET /api/session-messages`：按会话读取 SQLite 历史消息
- `GET /api/memory/status`：查询会话 token 分区与刷盘状态
- `GET /api/memory/files`：读取全部记忆文件
- `POST /api/memory/reset`：重置 memory 目录并按内置初始内容覆盖
- `PUT /api/memory/files/{file_name}`：人工编辑记忆文件
- `POST /api/memory/flush`：手动触发刷盘

详细参数请查看：`docs/api_reference.md`

## 7. 文档索引

- 架构说明：`docs/architecture.md`
- 接口文档：`docs/api_reference.md`
- 核心模块：`docs/core_modules.md`
- 前端说明：`docs/frontend_guide.md`

## 8. 常见问题

## 8.1 启动时报缺少依赖

请先执行：

```bash
python -m pip install -r requirements.txt
```

## 8.2 为什么后端没有 `.env`

这是刻意设计：后端保持无状态，模型参数由前端每次请求透传，便于切换供应商与模型。

## 8.3 为什么 `系统提示词.md` 不能被工具改写

为了防止模型自我漂移，避免底层规则被自动覆盖。该文件仅允许人工接口编辑。

## 9. 开发建议

- 先阅读 `docs/architecture.md` 再修改核心逻辑
- 修改工具行为时同步更新 `docs/core_modules.md`
- 修改接口字段时同步更新 `docs/api_reference.md` 与前端 `static/app.js`
