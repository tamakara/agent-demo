# 文档总览（重构版）

当前文档按“高内聚、低耦合”重组为 6 个主文档，每个文档只承担一个清晰边界。

## 1. 推荐阅读顺序

1. [system_design.md](system_design.md)：系统目标、分层依赖、模块职责、架构约束
2. [state_and_persistence.md](state_and_persistence.md)：状态机、token 预算、持久化模型、刷盘规则
3. [api_and_streaming.md](api_and_streaming.md)：HTTP 契约与 SSE 协议
4. [prompt_system.md](prompt_system.md)：提示词模板、注入映射、运行链路
5. [frontend_integration.md](frontend_integration.md)：前端接入与状态管理
6. [image_pipeline.md](image_pipeline.md)：文生图与素材流转工具

## 2. 文档边界

- 架构与分层原则只在 `system_design.md` 维护
- 会话/刷盘/token/数据模型只在 `state_and_persistence.md` 维护
- HTTP/SSE 契约只在 `api_and_streaming.md` 维护
- 提示词结构与模板只在 `prompt_system.md` 维护
- 前端实现建议只在 `frontend_integration.md` 维护
- 图片工具规范只在 `image_pipeline.md` 维护

## 3. 迁移映射（旧 -> 新）

- `architecture.md` -> `system_design.md`
- `layering.md` -> `system_design.md`
- `core_modules.md` -> `system_design.md`
- `multi_user.md` -> `system_design.md` + `state_and_persistence.md`
- `data_model.md` -> `state_and_persistence.md`
- `session_window_and_flush.md` -> `state_and_persistence.md`
- `token_calculation.md` -> `state_and_persistence.md`
- `api_reference.md` -> `api_and_streaming.md`
- `sse_protocol.md` -> `api_and_streaming.md`
- `prompt_structure.md` -> `prompt_system.md`
- `llm_prompt_sources.md` -> `prompt_system.md`
- `frontend_guide.md` -> `frontend_integration.md`
- `image_tooling.md` -> `image_pipeline.md`
