# 前端使用说明（`static/`，多用户版）

## 1. 页面初始化

`app.js` 在 `bootstrap()` 开始时会执行 `promptForUserId()`：

1. 强制弹窗输入 `user_id`
2. 为空或不符合规则时要求重输
3. 输入成功后才会加载会话、配置和记忆文件

校验规则与后端保持一致：

- `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`

## 2. 当前用户与切换用户

页面顶部展示当前用户：

- `当前用户：<user_id>`

支持点击“切换用户”按钮：

1. 再次弹窗输入 `user_id`
2. 清空当前聊天显示
3. 重新加载该用户的 session、设置、记忆文件和状态

## 3. API 调用约定

前端统一通过 `buildUserQuery()` 或请求体附带 `user_id`。

### query 传递 `user_id`

- `GET /api/sessions`
- `GET /api/session-messages`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/memory/status`
- `GET /api/memory/files`
- `POST /api/memory/reset`
- `PUT /api/memory/files/{file_name}`

### body 传递 `user_id`

- `POST /api/sessions`
- `POST /api/chat`
- `POST /api/memory/flush`

## 4. 会话与聊天

会话逻辑与单用户版一致，但数据作用域变为“当前 `user_id`”：

1. 如果当前用户没有 session，自动创建一个
2. 切换 session 后仅加载该用户该 session 的历史消息
3. 聊天和刷盘都作用于当前用户上下文

## 5. Token 仪表盘

仪表盘显示项新增 `user_id`，并持续轮询：

- `user id`
- `session id`
- token 使用与预算
- 刷盘状态

轮询间隔保持 `6s`。

## 6. 记忆文件编辑

记忆文件编辑区操作目标为：

`data/user/<user_id>/memory/`

重置按钮同样只影响当前用户目录，不影响其他用户数据。
