# agent-demo

一个基于 FastAPI 的多用户记忆智能体演示项目，当前版本重点是：

1. 根目录分层结构（`api / app / domain / infra / common`）
2. 端口-适配器设计（Ports & Adapters）
3. 统一 API JSON Envelope + SSE Envelope
4. 数字员工级 token 预算与自动/手动刷盘

## 1. 目录结构

```text
agent-demo/
├── main.py
├── run.py
├── requirements.txt
├── api/        # HTTP 路由、请求 DTO、SSE 输出
├── app/        # 用例编排、业务服务、端口接口
├── domain/     # 领域规则（预算、协议、模型）
├── infra/      # SQLite/文件系统/LLM/工具实现
├── common/     # 错误、响应封装、ID/时间工具
├── prompts/    # system 模板与底层提示词（聊天/工具调用/刷盘）
├── static/     # 前端页面
└── docs/       # 分文件文档（按专题独立维护）
```

## 2. 核心能力

- 多用户隔离（`user_id`）
- 数字员工管理（创建、列表、历史消息）
- 员工级会话隔离（每个员工绑定唯一 `session_id`）
- 流式聊天（`POST /chat/stream`，SSE）
- 工具调用（读写记忆文件、获取系统时间）
- 员工记忆文件管理（读取、覆盖、重置）
- token 分区统计与刷盘（自动 + 手动）

## 3. 运行方式

### 3.1 安装依赖

```bash
python -m pip install -r requirements.txt
```

### 3.2 启动服务

```bash
python run.py
```

默认地址：

- 前端：`http://127.0.0.1`
- OpenAPI：`http://127.0.0.1/docs`

## 4. API 与协议约定

- 无路径前缀：不使用 `/api`、`/v1`
- `user_id` 传递：
1. 查询接口走 query
2. 写接口优先走 body
3. `PUT /memory/files/{file_name}` 与 `POST /memory/reset` 保持 query

统一 JSON 响应：

```json
{
  "request_id": "...",
  "ts": "...",
  "data": {}
}
```

统一 SSE 事件包：

```json
{
  "type": "assistant_final",
  "seq": 10,
  "request_id": "...",
  "ts": "...",
  "employee_id": "1",
  "session_id": "employee-1",
  "payload": {}
}
```

## 5. 关键接口

- `GET /employees`：列出用户数字员工
- `POST /employees`：创建新数字员工（自动分配下一个编号）
- `GET /employee-messages`：读取指定员工历史消息
- `POST /chat/stream`：员工上下文流式对话
- `GET /memory/files`：返回员工数据目录、目录树与记忆文件内容

## 6. 文档入口

文档已按专题拆分，见：

- [docs/README.md](docs/README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/layering.md](docs/layering.md)
- [docs/api_reference.md](docs/api_reference.md)
- [docs/sse_protocol.md](docs/sse_protocol.md)
- [docs/data_model.md](docs/data_model.md)
- [docs/frontend_guide.md](docs/frontend_guide.md)
- [docs/multi_user.md](docs/multi_user.md)
- [docs/core_modules.md](docs/core_modules.md)
- [docs/testing.md](docs/testing.md)

## 7. 兼容说明

本版本不兼容旧版会话 API（`/sessions`、`/session-messages`），不提供旧实现兼容层。
