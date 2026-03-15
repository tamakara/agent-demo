# Prompts 目录说明

本目录采用“模板 + 片段”组织，便于按调用类型维护提示词。

## 目录结构

- `templates/`：提示词框架文件（只放占位符结构）
- `sections/`：可复用片段（角色定义、工具策略、任务说明）

## 调用类型与入口

1. 数字员工会话（chat.completions）
- 模板：`templates/chat_system.md`
- 片段：`sections/chat_system_base.md`、`sections/tool_calling.md`、`sections/image_tool_calling.md`
- 动态注入：窗口预算、工具清单、记忆文件、工作台摘要

2. 归档刷盘（chat.completions）
- 模板：`templates/flush_archive_system.md`
- 片段：`sections/flush_archive.md`
- 动态注入：会话常驻 system 文本

3. 画图模型（images.generate）
- 模板：`templates/image_generation.md`
- 片段：`sections/image_generation_base.md`
- 动态注入：用户原始画图需求

## 占位符规则

模板占位符统一使用 `{{VARIABLE_NAME}}`。
代码会在运行时按变量名执行字符串替换。
