# 文档总览

本文档目录按“单主题、低耦合”拆分，每个文件只回答一类问题。

## 阅读顺序（推荐）

1. [architecture.md](architecture.md)：系统目标与总体结构
2. [layering.md](layering.md)：分层依赖与端口-适配器规则
3. [api_reference.md](api_reference.md)：HTTP 接口契约
4. [sse_protocol.md](sse_protocol.md)：流式事件协议
5. [data_model.md](data_model.md)：数据库与文件结构
6. [multi_user.md](multi_user.md)：多用户隔离规则
7. [frontend_guide.md](frontend_guide.md)：前端接入与状态管理
8. [core_modules.md](core_modules.md)：模块职责清单
9. [testing.md](testing.md)：测试策略与执行方式

## 文档边界说明

- API 路由字段仅在 `api_reference.md` 维护
- SSE 字段与事件顺序仅在 `sse_protocol.md` 维护
- 数据表与目录结构仅在 `data_model.md` 维护
- 前端行为仅在 `frontend_guide.md` 维护

通过上述边界，避免同一规则在多个文件重复维护。
