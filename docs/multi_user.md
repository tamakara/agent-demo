# 多用户隔离说明

## 本文范围

本文只覆盖多用户隔离模型，不覆盖接口字段细节。

## 1. 核心原则

系统不做鉴权，`user_id` 直接作为租户隔离键。

隔离对象：

1. 数字员工（employees -> sessions）
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
- `session_id` 命名：`employee-{employee_id}`
- `messages` 通过 `(user_id, session_id)` 关联
- `app_settings` 主键：`user_id`

### 3.2 文件系统

目录：`data/user/<user_id>/`

包含：

- `employee/`
- `brand_library/`
- `skill_library/`

`employee/` 下按员工编号创建目录：

- `employee/1/`、`employee/2/` ...

每个员工目录都独立拥有：

- `memory.md`
- `notebook/`（`file.md`、`schedule.md`、`soul.md`、`workbook.md`）
- `workspace/`
- `skills/`

隔离粒度：

- 不同 `user_id` 的员工目录互不可见
- 同一 `user_id` 下不同 `employee_id` 的记忆文件互不共享

## 4. 运行时隔离

- 锁粒度为 `(user_id, session_id)`
- 不同用户同名员工编号不会互相阻塞
- 同一用户不同员工编号也不会互相阻塞

## 5. 参数传递约束

- 查询接口使用 query `user_id`
- 员工上下文接口同时传递 `employee_id`
- 写接口优先 body `user_id`
- 不允许路径参数 `/{user_id}`

## 6. 验证用例

1. `alice` 与 `bob` 各自默认创建员工 `1`
2. 双方员工 `1` 消息互不可见
3. `alice` 创建员工 `2` 后，员工 `1`/`2` 记忆文件相互独立
4. 双方 settings 独立保存
5. 双方刷盘状态独立变化
