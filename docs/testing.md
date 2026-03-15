# 测试与质量门禁

## 本文范围

本文仅覆盖当前测试执行方式、覆盖范围与发布前检查项。

## 1. 测试命令

```bash
python -m unittest discover -s tests -v
```

## 2. 当前测试文件

- `tests/test_api_routes.py`
- `tests/test_domain_dependencies.py`
- `tests/test_prompt_composer.py`

## 3. 覆盖维度

### 3.1 API 契约

- 三模块新路由是否注册到 OpenAPI

### 3.2 架构边界

- `domain` 层不允许直接依赖 `infra` 层

### 3.3 Prompt 行为

- `PromptComposer` 通过注入的 `tool_schemas` 生成工具定义段落

## 4. 发布前检查清单

1. 单元测试全绿
2. OpenAPI 路径与 `docs/api_reference.md` 一致
3. 前端无旧路径请求残留（如 `/users/{user_id}/...`）
4. 文档索引与实际文件同步
