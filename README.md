# agent-demo

一个基于 FastAPI 的多用户记忆智能体演示项目，当前版本重点是：

1. 根目录分层结构（`api / app / domain / infra / common`）
2. 三模块组织（`chat / user / storage`）
3. 端口-适配器设计（Ports & Adapters）
4. 统一 API JSON Envelope + SSE Envelope
4. 数字员工级 token 预算与自动/手动刷盘

## 1. 目录结构

```text
agent-demo/
├── main.py
├── run.py
├── requirements.txt
├── api/        # 路由装配 + chat/user/storage 子路由
├── app/        # chat/user/storage 应用服务与用例
├── domain/     # 领域规则（提示词、预算、协议、模型）
├── infra/      # chat/user/storage 基础设施适配器
├── common/     # 错误、响应封装、ID/时间工具
├── prompts/    # 提示词目录（templates + sections，按调用类型维护）
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
- 资源路径采用三模块组织：
1. `user`：`/user/...`
2. `chat`：`/chat/...`
3. `storage`：`/storage/...`
- `user_id` / `employee_id` 通过 query 或 body 提供，不再固定在路径中

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

- `GET /user/employees?user_id=...`：列出用户数字员工
- `POST /user/employees`：创建新数字员工（body 携带 `user_id`）
- `GET /user/employee-messages?user_id=...&employee_id=...`：读取指定员工历史消息
- `POST /chat/stream`：流式对话（body 携带 `user_id`、`employee_id`、`message`）
- `GET /storage/tree?user_id=...`：返回用户数据目录树与可编辑记忆文件

## 6. 文档入口

文档已按专题拆分，见：

- [docs/README.md](docs/README.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/layering.md](docs/layering.md)
- [docs/api_reference.md](docs/api_reference.md)
- [docs/sse_protocol.md](docs/sse_protocol.md)
- [docs/data_model.md](docs/data_model.md)
- [docs/session_window_and_flush.md](docs/session_window_and_flush.md)
- [docs/frontend_guide.md](docs/frontend_guide.md)
- [docs/multi_user.md](docs/multi_user.md)
- [docs/core_modules.md](docs/core_modules.md)
- [docs/testing.md](docs/testing.md)
