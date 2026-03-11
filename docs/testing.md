# 测试与质量门禁

## 本文范围

本文仅覆盖测试执行方式、覆盖范围与发布前检查项。

## 1. 测试命令

```bash
python -m unittest discover -s tests -v
```

## 2. 当前测试文件

- `tests/test_window_policy.py`
- `tests/test_tool_protocol.py`
- `tests/test_sse.py`
- `tests/test_api_contract.py`
- `tests/test_docs_consistency.py`

## 3. 覆盖维度

### 3.1 Domain 单元

- token 预算分配
- tool 协议清洗

### 3.2 API 集成

- `/sessions`
- `/settings`
- `/memory/files`
- `/memory/status`

### 3.3 协议契约

- SSE envelope 结构
- 文档与代码关键路径一致性

## 4. 发布前检查清单

1. 单元+集成测试全绿
2. OpenAPI 路径与文档一致
3. 前端无 `/api/*` 与 `/v1/*` 残留请求
4. 文档索引与实际文件同步

## 5. 建议补充项

1. 为 `chat/stream` 增加真实流式集成测试
2. 为刷盘流程增加失败回滚场景测试
3. 为并发场景增加多会话压力测试
