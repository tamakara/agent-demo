# 文生图工具与素材流转

本文档描述 agent 内置图片工具的调用约定、落盘路径和结果结构。

## 目标

- agent 可通过工具 `image_gen_edit` 调用 `seedream-4-5` 执行文生图。
- 图片先保存到员工数据目录 `/employee/{employee_id}/workspace`。
- 生成完成后，可再调用工具 `copy_workspace_image_to_brand_library` 复制到用户目录 `/brand_library`。

## 工具清单

### 1) `image_gen_edit`

用途：调用 OpenAI 兼容接口 `v1/images/generations` 生成单张图片并落盘到员工 workspace。

关键行为：
- 模型固定为 `seedream-4-5`。
- 为兼容 `seedream-4-5` 参数能力，请求中不再传 `output_format` 参数，避免上游 `InvalidParameter`。
- `api_key/base_url` 复用当前会话的 LLM 配置（与聊天模型同一套鉴权和网关）。
- 通过 OpenAI Python SDK `client.images.generate(...)` 发起请求，等价于请求路径 `POST {base_url}/images/generations`。
- 工具内部使用 `response_format=b64_json`，将返回内容解码并保存为本地文件。

参数：
- `nameHint` (`string`, 必填)：输出文件名提示词，用于生成 workspace 文件名。
- `imagePath` (`string[]`, 选填)：参考图路径数组，可空。
- `prompt` (`string`, 必填)：文生图提示词。
- `aspectRatio` (`string`, 选填)：比例，支持 `auto` 或 `1:1`、`16:9` 等格式。
- `resolution` (`string`, 选填)：分辨率档位，支持 `2K`/`4K`，默认 `2K`。

返回（工具结果中的 JSON 字符串）包含：
- `workspace_file_name`
- `workspace_relative_path`（例如 `/employee/1/workspace/xxx.png`）
- `workspace_abs_path`
- `model`（固定 `seedream-4-5`）
- `endpoint`（`.../images/generations`）
- `name_hint` / `image_paths`
- `aspect_ratio` / `resolution` / `output_format`
- `bytes`
- `revised_prompt`

### 2) `copy_workspace_image_to_brand_library`

用途：将员工 workspace 下已有图片复制到用户 brand library。

参数：
- `workspace_file_name` (`string`, 必填)：源图片文件名。
- `brand_file_name` (`string`, 选填)：目标文件名；不传则沿用源文件名。

返回（工具结果中的 JSON 字符串）包含：
- `workspace_file_name`
- `workspace_relative_path`
- `brand_file_name`
- `brand_relative_path`（例如 `/brand_library/xxx.png`）
- `brand_abs_path`

## 推荐调用顺序

1. 调用 `image_gen_edit` 生成图片并写入 `/employee/{employee_id}/workspace`。
2. 从返回结果取 `workspace_file_name`。
3. 调用 `copy_workspace_image_to_brand_library`，将同名文件复制到 `/brand_library`。

## 目录展示变化

`/memory/files` 的目录树输出现在会额外展示以下图片后缀：

- `.png`
- `.jpeg`
- `.jpg`
- `.webp`

展示范围：
- `/employee/{employee_id}/workspace`
- `/brand_library`
