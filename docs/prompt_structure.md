# 提示词结构总览（统一版）

本文档是提示词结构的单一事实来源，合并了原有提示词结构说明，并补充了当前最新模板内容。

## 1. 目标与范围

提示词体系采用“模板 + 片段 + 运行时注入”三段式：

1. `templates/` 负责定义结构骨架（XML 标签 + 占位符）。
2. `sections/` 负责维护可复用内容（角色、策略、任务说明）。
3. `domain/prompt_templates.py` 负责读取文件并注入变量，输出最终请求文本。

## 2. 当前目录结构

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

## 3. 最新模板内容（XML）

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

## 4. 占位符注入映射（运行时）

注入实现位于 `domain/prompt_templates.py`，核心规则如下。

| 模板 | 占位符 | 数据来源 |
|---|---|---|
| `chat.xml` | `BASE_PROMPT` | `window_preamble` + `chat_base_prompt.md` |
| `chat.xml` | `TOOLS_PROMPT` | `tools_base_prompt.md` 注入 `TOOL_DEFINITIONS` 后的结果 |
| `chat.xml` | `SOUL_NOTEBOOK_PROMPT` | 记忆文件 `soul.md` |
| `chat.xml` | `WORKBOOK_NOTEBOOK_PROMPT` | 记忆文件 `workbook.md` |
| `chat.xml` | `SCHEDULE_NOTEBOOK_PROMPT` | 记忆文件 `schedule.md` |
| `chat.xml` | `MEMORY_PROMPT` | 记忆文件 `memory.md`（压缩记忆） |
| `compression.xml` | `BASE_PROMPT` | 常驻 system 文本 `resident_base_system` |
| `compression.xml` | `ARCHIVE_TASK_PROMPT` | `compression_base_prompt.md` |
| `image_generation.xml` | `BASE_PROMPT` | `image_generation_base_prompt.md` |
| `image_generation.xml` | `USER_PROMPT` | 工具参数中的用户原始画图需求 |

## 5. 三类调用与入口

| 调用类型 | 模板文件 | 片段文件 | 入口函数 |
|---|---|---|---|
| 聊天（chat） | `prompts/templates/chat.xml` | `chat_base_prompt.md` + `tools_base_prompt.md` | `compose_chat_system_prompt(...)` |
| 归档压缩（compression） | `prompts/templates/compression.xml` | `compression_base_prompt.md` | `compose_flush_archive_system_prompt(...)` |
| 文生图（image_generation） | `prompts/templates/image_generation.xml` | `image_generation_base_prompt.md` | `compose_image_generation_prompt(...)` |

## 6. 拼装流程摘要

### 6.1 聊天主链路

1. 写入本轮用户消息（`dialogue` 或 `buffer`）。
2. 收集上下文：窗口预算、工具 schema、记忆文件、工作台摘要。
3. 执行 `compose_chat_system_prompt(...)` 生成 system 提示词。
4. 与历史消息拼接后请求 `chat.completions`。

### 6.2 归档压缩链路

1. 先生成常驻 `base_system`。
2. 执行 `compose_flush_archive_system_prompt(...)` 注入 `compression.xml`。
3. 以归档对话为输入调用 `chat.completions` 生成摘要并落盘。

### 6.3 画图链路

1. 接收 `image_gen_edit` 的用户需求参数。
2. 执行 `compose_image_generation_prompt(...)` 注入 `image_generation.xml`。
3. 将结果发送到 `images.generate`。

## 7. 关键约束与维护规则

1. 模板只维护结构，不写具体策略内容。
2. 片段只维护语义内容，不关心调用链路。
3. 新增调用类型时，先加 `templates/<type>.xml`，再加 `sections/*_base_prompt.md`，最后在 `domain/prompt_templates.py` 增加 `compose_*`。
4. 模板占位符统一使用 `{{VARIABLE_NAME}}`，由 `render_prompt_template(...)` 做字符串替换。
5. 与窗口预算相关的实现细节，参考 `docs/token_calculation.md` 与 `docs/session_window_and_flush.md`。

## 8. 关键实现文件

- `domain/prompt_templates.py`：模板读取、片段读取、占位符注入。
- `domain/prompt_composer.py`：聊天常驻 system 文本拼装与预算裁剪。
- `app/chat/services/memory_context_service.py`：聊天与刷盘主流程。
- `infra/tools/image_tool.py`：画图工具请求构造与落地。
