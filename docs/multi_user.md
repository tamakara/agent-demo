# 多用户功能说明

## 1. 设计目标

实现一个简单的多用户能力，不引入身份认证，仅通过 `user_id` 标识用户，并做到：

1. 对话隔离
2. 记忆文件隔离
3. 设置隔离
4. 刷盘状态隔离

## 2. 用户标识规则

`user_id` 必须满足：

- 正则：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
- 只允许字母、数字、点、下划线、短横线
- 不能包含路径分隔符或空白 ID

## 3. 存储隔离

### 3.1 SQLite

- 会话主键：`(user_id, session_id)`
- 消息外键：`(user_id, session_id)`
- 设置主键：`user_id`

### 3.2 文件系统

记忆目录按用户拆分：

`data/memory/<user_id>/`

用户首次访问时自动写入初始模板文件。

## 4. 接口调用要求

### 4.1 必须携带 `user_id`

- 列表/查询接口：通过 query 传 `user_id`
- 创建/动作接口：通过 body 或 query 传 `user_id`

### 4.2 关键接口示例

获取会话列表：

`GET /api/sessions?user_id=alice`

创建会话：

```json
POST /api/sessions
{
  "user_id": "alice",
  "session_id": ""
}
```

流式聊天：

```json
POST /api/chat
{
  "user_id": "alice",
  "session_id": "default",
  "message": "你好",
  "max_tool_rounds": 6,
  "llm_config": {
    "model": "agent-advoo",
    "api_key": "sk-...",
    "base_url": "http://model-gateway.test.api.dotai.internal/v1"
  }
}
```

## 5. 前端行为

1. 页面加载即弹窗输入 `user_id`
2. 未输入合法 `user_id` 不会继续初始化
3. 顶部展示当前用户
4. 可通过“切换用户”重新加载对应数据视图

## 6. 不兼容说明

当前实现按需求明确“不兼容旧版本代码和数据库”：

- 未提供迁移脚本
- 旧单用户结构不做自动兼容
- 建议使用新数据库文件或清理旧 `data/agent_state.db`

## 7. 验证建议

可用两个用户做快速验证：

1. 用户 `alice` 创建 session 并发送消息
2. 切到用户 `bob`，确认看不到 `alice` 的 session 与消息
3. 在 `alice` 修改记忆文件，切 `bob` 后确认文件内容不同
4. 两个用户分别保存不同 `settings`，确认互不覆盖
