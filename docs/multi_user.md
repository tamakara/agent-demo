# 多用户隔离说明

## 本文范围

本文只覆盖多用户隔离模型，不覆盖接口字段细节。

## 1. 核心原则

系统不做鉴权，`user_id` 直接作为租户隔离键。

隔离对象：

1. 会话（sessions）
2. 消息（messages）
3. 配置（app_settings）
4. 记忆文件（data/user/<user_id>）
5. 刷盘状态与会话锁

## 2. user_id 规则

- 正则：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
- 仅允许字母、数字、`.`、`_`、`-`
- 必须以字母或数字开头

## 3. 数据层隔离

### 3.1 SQLite

- `sessions` 主键：`(user_id, session_id)`
- `messages` 通过 `(user_id, session_id)` 关联
- `app_settings` 主键：`user_id`

### 3.2 文件系统

目录：`data/user/<user_id>/`

包含：

- `memory/`
- `brand_library/`
- `skill_library/`

## 4. 运行时隔离

- 锁粒度为 `(user_id, session_id)`
- 不同用户同名会话不会互相阻塞

## 5. 参数传递约束

- 查询接口使用 query `user_id`
- 写接口优先 body `user_id`
- 不允许路径参数 `/{user_id}`

## 6. 验证用例

1. `alice` 和 `bob` 分别创建同名 `session_id`
2. 双方消息互不可见
3. 双方记忆文件修改互不影响
4. 双方 settings 独立保存
5. 双方刷盘状态独立变化
