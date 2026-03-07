# 前端使用说明（`static/`）

## 1. 页面结构

`index.html` 包含四个核心区域：

1. 设置面板（LLM + 上下文容量）
2. token 仪表盘
3. 聊天与工具控制台（含 `session id` 选择与新建）
4. 记忆文件监视与编辑区域

## 2. 全局设置持久化（SQLite）

前端不再使用 localStorage。配置以全局单例形式存储在 SQLite 的 `app_settings` 表中，与 `session id` 无关。

配置字段：

- `model`（model name）
- `api_key`
- `base_url`
- `max_tool_rounds`
- `total_token_limit`（上下文总容量，默认 200000）

项目预置默认值：

- `model = agent-advoo`
- `base_url = http://model-gateway.test.api.dotai.internal/v1`
- `api_key` 预置为后端默认值（可在设置面板覆盖）

前端接口流程：

1. 页面初始化时调用 `GET /api/settings` 回填表单。
2. 点击“保存配置”调用 `PUT /api/settings` 持久化配置。
3. `POST /api/chat` 与 `POST /api/memory/flush` 会携带当前表单中的配置。

`base_url` 推荐填写：

1. OpenAI 官方：`https://api.openai.com/v1`
2. OpenAI 兼容服务：`https://你的服务域名/v1`

补充说明：

1. 若填 `.../v1/chat/completions`，后端会自动规范化为 `.../v1`。
2. 若只填域名，后端会自动补 `/v1`。

## 3. session 管理

会话相关接口：

1. `GET /api/sessions`：加载 session 列表
2. `POST /api/sessions`：创建新 session 并持久化到 SQLite

交互规则：

1. 会话下拉框用于切换当前 session。
2. “新建会话”按钮会创建并自动切换到新 session。
3. 切换 session 后会拉取 SQLite 历史消息并刷新 token 状态，不会切换全局设置。

## 4. 聊天请求与 SSE 解析

前端通过 `fetch(POST /api/chat)` 获取流式响应，并手动解析：

- `event:` 事件名
- `data:` 事件负载

展示规则：

- `tool_call` / `tool_result` 显示在控制台日志区域
- `assistant_final` 作为本轮最终回答
- `memory_status` 用于刷新 token 仪表盘

## 5. token 仪表盘更新

通过 `GET /api/memory/status` 获取状态并更新三段进度条：

- `residentBar`：常驻区
- `dialogueBar`：对话区
- `bufferBar`：缓冲区

页面默认每 6 秒轮询一次；聊天结束和刷盘动作后也会立即刷新。

## 6. 记忆文件编辑流程

流程如下：

1. 调用 `GET /api/memory/files` 拉取文件列表与内容
2. 点击文件标签后在编辑器修改内容
3. 调用 `PUT /api/memory/files/{file_name}` 提交保存（前端固定使用 `overwrite`）
4. 点击“重置”按钮调用 `POST /api/memory/reset`，清空 `data/memory` 后用后端内置初始内容覆盖

特殊说明：

- `系统提示词.md` 允许人工编辑（通过该接口）
- 模型工具层禁止写入 `系统提示词.md`

## 7. 手动刷盘

点击“手动刷盘”后调用 `POST /api/memory/flush`：

- 空闲会话会返回 `accepted=true` 并启动后台任务
- 正在刷盘的会话返回 `accepted=false`
