# 模块职责清单

## 本文范围

本文仅回答“模块做什么”，不描述 API 字段和数据库字段。

## 1. 三大业务模块

- `chat`：对话、LLM 调用、提示词、token 预算、记忆状态、刷盘
- `user`：用户配置、员工生命周期管理、员工历史消息
- `storage`：用户文件目录树、文件读写删、图片预览、素材上传

## 2. API 层（`api`）

- `api/routes.py`：装配三模块路由
- `api/routes_user.py`：`/user/settings|employees...`
- `api/routes_chat.py`：`/chat/stream` 与 `/chat/memory/*`
- `api/routes_storage.py`：`/storage/*` 文件接口
- `api/routes_shared.py`：跨路由共享校验与响应辅助

## 3. App 层（`app`）

- `app/chat/services/memory_context_service.py`：聊天记忆核心服务
- `app/chat/services/session_lock_registry.py`：会话并发锁管理
- `app/chat/services/window_config_service.py`：窗口阈值与 tokenizer 读取
- `app/chat/use_cases/*`：chat 用例入口
- `app/user/services/*`：用户设置与员工管理服务
- `app/storage/services/*`：文件能力服务

## 4. Domain 层（`domain`）

- `domain/prompt_composer.py`：system 提示词拼装与窗口裁剪
- `domain/chat/memory_files.py`：记忆文件名与相对路径规则
- `domain/window_policy.py`：token 阈值策略
- `domain/tool_protocol.py`：工具协议清洗与还原
- `domain/models.py`：跨模块领域模型

## 5. Infra 层（`infra`）

- `infra/chat/*`：LLM 网关与 tokenizer 适配
- `infra/user/*`：SQLite 仓储适配
- `infra/storage/*`：文件仓储与目录布局适配
- `infra/tools/*`：工具执行、schema、时间服务
