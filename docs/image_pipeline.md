# 文生图工具与素材流转

## 1. 文档目标

本文档说明图片相关工具的调用契约、落盘位置与推荐流程。

## 2. 工具一：`image_gen_edit`

用途：调用 `images.generate` 生成单张图片并保存到员工 `workspace`。

实现要点：

1. 模型固定 `seedream-4-5`。
2. 请求不传 `output_format`，避免上游参数错误。
3. 复用当前会话的 `api_key/base_url`。
4. 采用 `response_format=b64_json`，解码后写本地文件。

参数：

- `nameHint`（必填）：输出文件名提示
- `prompt`（必填）：文生图提示词
- `imagePath`（选填）：参考图路径数组
- `aspectRatio`（选填）：`auto` 或 `1:1`、`16:9` 等
- `resolution`（选填）：`2K` 或 `4K`（默认 `2K`）

结果字段（工具返回 JSON）：

- `workspace_file_name`
- `workspace_relative_path`
- `workspace_abs_path`
- `model`
- `endpoint`
- `name_hint`
- `image_paths`
- `aspect_ratio`
- `resolution`
- `bytes`
- `revised_prompt`

## 3. 工具二：`copy_workspace_image_to_brand_library`

用途：将员工 `workspace` 中的图片复制到用户 `brand_library`。

参数：

- `workspace_file_name`（必填）
- `brand_file_name`（选填）

结果字段：

- `workspace_file_name`
- `workspace_relative_path`
- `brand_file_name`
- `brand_relative_path`
- `brand_abs_path`

## 4. 推荐调用顺序

1. 调用 `image_gen_edit` 生成图片，写入 `/employee/{employee_id}/workspace`。
2. 从结果中读取 `workspace_file_name`。
3. 需要沉淀素材时，再调用 `copy_workspace_image_to_brand_library` 复制到 `/brand_library`。

## 5. 目录展示与可见性

`/storage/tree` 对以下后缀提供图片展示：

- `.png`
- `.jpeg`
- `.jpg`
- `.webp`

展示范围：

- `/employee/{employee_id}/workspace`
- `/brand_library`
