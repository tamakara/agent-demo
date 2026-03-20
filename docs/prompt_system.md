# 提示词系统

## 1. 文档目标

本文档是提示词体系的单一事实来源，覆盖：

- 模板与片段目录结构
- 最新 XML 模板结构
- 运行时占位符注入映射
- 三类调用链路与维护规则

## 2. 目录结构

```text
prompts/
├── templates/
│   ├── chat.xml
│   ├── compression.xml
│   └── image_generation.xml
└── sections/
    ├── chat_base_prompt.md
    ├── tools_base_prompt.md
    ├── compression_base_prompt.md
    └── image_generation_base_prompt.md
```

职责分工：

1. `templates/`：结构骨架（XML 标签 + 占位符）。
2. `sections/`：可复用语义片段（角色、策略、任务说明）。
3. `domain/prompt_templates.py`：读取并注入变量，生成最终 prompt。

## 3. 最新模板结构

### 3.1 `chat.xml`

```xml
<chat_prompt>
    <base>
        {{BASE_PROMPT}}
    </base>
    <tools>
        {{TOOLS_PROMPT}}
    </tools>
    <notebook>
        <file>
            {{FILE_NOTEBOOK_PROMPT}}
        </file>
        <soul>
            {{SOUL_NOTEBOOK_PROMPT}}
        </soul>
        <workbook>
            {{WORKBOOK_NOTEBOOK_PROMPT}}
        </workbook>
        <schedule>
            {{SCHEDULE_NOTEBOOK_PROMPT}}
        </schedule>
    </notebook>
    <memory>
        {{MEMORY_PROMPT}}
    </memory>
</chat_prompt>
```

### 3.2 `compression.xml`

```xml
<compression_prompt>
    <tools>
        {{TOOLS_PROMPT}}
    </tools>
    <archive_task>
        {{ARCHIVE_TASK_PROMPT}}
    </archive_task>
</compression_prompt>
```

### 3.3 `image_generation.xml`

```xml
<image_generation_prompt>
    <base>
        {{BASE_PROMPT}}
    </base>
    <user_request>
        {{USER_PROMPT}}
    </user_request>
</image_generation_prompt>
```

## 4. 占位符注入映射

注入函数位于 `domain/prompt_templates.py`。

| 模板 | 占位符 | 来源 |
|---|---|---|
| `chat.xml` | `BASE_PROMPT` | `window_preamble` + `chat_base_prompt.md` |
| `chat.xml` | `TOOLS_PROMPT` | `tools_base_prompt.md` 注入 `TOOL_DEFINITIONS` |
| `chat.xml` | `FILE_NOTEBOOK_PROMPT` | `file.md` |
| `chat.xml` | `SOUL_NOTEBOOK_PROMPT` | `soul.md` |
| `chat.xml` | `WORKBOOK_NOTEBOOK_PROMPT` | `workbook.md` |
| `chat.xml` | `SCHEDULE_NOTEBOOK_PROMPT` | `schedule.md` |
| `chat.xml` | `MEMORY_PROMPT` | `.memory/memory.md` |
| `compression.xml` | `TOOLS_PROMPT` | `tools_base_prompt.md` 注入 `TOOL_DEFINITIONS` |
| `compression.xml` | `ARCHIVE_TASK_PROMPT` | `compression_base_prompt.md` |
| `image_generation.xml` | `BASE_PROMPT` | `image_generation_base_prompt.md` |
| `image_generation.xml` | `USER_PROMPT` | 用户画图请求 |

补充约定：

- 记忆文件规格（相对路径、token 比例）集中定义在 `domain/chat/memory_files.py` 的 `MANAGED_MEMORY_FILE_SPECS`
- 受管记忆文件预算合计 9%（`MANAGED_MEMORY_FILES_RATIO`）
- 固定提示词预算 1%（`SYSTEM_PROMPT_FIXED_RATIO`，不做硬限制）
- 两者共同组成 `system_prompt_limit` 的 10%（`SYSTEM_PROMPT_LIMIT_RATIO`）

## 5. 三类调用入口

- 聊天：`compose_chat_system_prompt(...)`
- 归档压缩：`compose_compression_system_prompt(tool_definitions=..., memory_file_path=..., memory_token_limit=...)`
- 文生图：`compose_image_generation_prompt(...)`

## 6. 运行时链路

### 6.1 聊天

1. 收集窗口预算、工具 schema、记忆文件、摘要。
2. 注入 `chat.xml` 生成 system prompt。
3. 与历史消息拼接后调用 `chat.completions`。

### 6.2 归档压缩

1. 注入 `compression.xml`：
   - `ARCHIVE_TASK_PROMPT` 来自 `compression_base_prompt.md`
   - `TOOLS_PROMPT` 来自 `tools_base_prompt.md`（含可用工具定义）
   - `compression_base_prompt.md` 会额外注入 `MEMORY_FILE_PATH` 与 `MEMORY_TOKEN_LIMIT`
2. 将旧 `dialogue` 区拼接为一段文本，作为归档 `user` 消息输入。
3. 用归档消息触发 `chat.completions`：读取当前 `memory.md`，以 `mode=overwrite` 覆盖写回更新后的 `memory.md`，最后输出压缩摘要。
4. 受管记忆文件 token 限制按 `total_token_limit` 比例统一在 `write_notebook_file` 工具写入时校验：
   - `memory.md`（`.memory/memory.md`）：5%
   - `file.md` / `soul.md` / `schedule.md` / `workbook.md`：各 1%
5. 受管记忆文件通常可用 `append` 增量更新；写入后会按最终文件大小校验。
6. 以上限制仅在 `write_notebook_file` 工具路径执行，不在其它链路做额外硬限制。
7. 若任一受管记忆文件写入超限会直接报错，Agent 需先读原文并继续压缩后再整体 overwrite 写回。
8. system_prompt 预算中的固定 1%（base + chat 模板固定内容）仅作预算参考，不做硬性校验。
9. 压缩记忆文件固定为 `employee/<id>/.memory/memory.md`；不兼容历史 `.memory.md` 单文件布局，也不做自动迁移。

### 6.3 文生图

1. 接收 `image_gen_edit` 参数中的用户需求。
2. 注入 `image_generation.xml`。
3. 调用 `images.generate` 生成图片。

## 7. 维护规则

1. 调整结构只改 `templates/*.xml`。
2. 调整语义只改 `sections/*_base_prompt.md`。
3. 新增类型时依次新增模板、片段、`compose_*` 函数。
4. 占位符统一格式：`{{VARIABLE_NAME}}`。
5. 模板渲染统一经 `render_prompt_template(...)`，禁止绕过渲染器手工拼接。


