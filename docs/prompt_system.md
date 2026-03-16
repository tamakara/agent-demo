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
<system_prompt>
    <base>
        {{BASE_PROMPT}}
    </base>
    <tools>
        {{TOOLS_PROMPT}}
    </tools>
    <notebook>
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
</system_prompt>
```

### 3.2 `compression.xml`

```xml
<flush_archive_system_prompt>
    <base>
        {{BASE_PROMPT}}
    </base>
    <archive_task>
        {{ARCHIVE_TASK_PROMPT}}
    </archive_task>
</flush_archive_system_prompt>
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
| `chat.xml` | `SOUL_NOTEBOOK_PROMPT` | `soul.md` |
| `chat.xml` | `WORKBOOK_NOTEBOOK_PROMPT` | `workbook.md` |
| `chat.xml` | `SCHEDULE_NOTEBOOK_PROMPT` | `schedule.md` |
| `chat.xml` | `MEMORY_PROMPT` | `memory.md` |
| `compression.xml` | `BASE_PROMPT` | `resident_base_system` |
| `compression.xml` | `ARCHIVE_TASK_PROMPT` | `compression_base_prompt.md` |
| `image_generation.xml` | `BASE_PROMPT` | `image_generation_base_prompt.md` |
| `image_generation.xml` | `USER_PROMPT` | 用户画图请求 |

## 5. 三类调用入口

- 聊天：`compose_chat_system_prompt(...)`
- 归档压缩：`compose_flush_archive_system_prompt(...)`
- 文生图：`compose_image_generation_prompt(...)`

## 6. 运行时链路

### 6.1 聊天

1. 收集窗口预算、工具 schema、记忆文件、摘要。
2. 注入 `chat.xml` 生成 system prompt。
3. 与历史消息拼接后调用 `chat.completions`。

### 6.2 归档压缩

1. 生成常驻 `base_system`。
2. 注入 `compression.xml`。
3. 用归档消息触发 `chat.completions`，产出摘要并写回记忆。

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
