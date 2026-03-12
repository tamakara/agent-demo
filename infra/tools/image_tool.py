"""图片工具服务：调用 OpenAI 文生图并处理本地文件落盘。"""

from __future__ import annotations

import base64
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiofiles
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from common.errors import NotFoundError, ValidationError
from domain.models import LLMConfig
from infra.llm.request_builder import normalize_openai_base_url
from infra.memory.storage_layout import user_brand_library_dir, user_employee_workspace_dir


IMAGE_GEN_MODEL = "seedream-4-5"
SUPPORTED_OUTPUT_FORMATS = {"png", "jpeg", "webp"}
SUPPORTED_FILE_SUFFIXES = {"png", "jpeg", "jpg", "webp"}
JPEG_SUFFIX_ALIASES = {"jpg": "jpeg"}
SUPPORTED_ASPECT_RATIOS = {"auto", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"}
ASPECT_RATIO_PATTERN = re.compile(r"^[1-9][0-9]?:[1-9][0-9]?$")
SUPPORTED_RESOLUTIONS = {"2K", "4K"}
DEFAULT_ASPECT_RATIO = "auto"
DEFAULT_RESOLUTION = "2K"
DEFAULT_OUTPUT_FORMAT = "png"
MAX_IMAGE_PATHS = 8


def _ensure_inside(base_dir: Path, target: Path, *, error_message: str) -> None:
    """校验目标路径必须在指定目录内，防止路径逃逸。"""
    if target == base_dir or base_dir in target.parents:
        return
    raise ValidationError(error_message)


class ImageToolService:
    """封装 seedream-4-5 文生图与文件复制能力。"""

    @staticmethod
    def _normalize_prompt(prompt: str) -> str:
        """校验提示词参数。"""
        text = str(prompt or "").strip()
        if not text:
            raise ValidationError("prompt 不能为空")
        return text

    @staticmethod
    def _normalize_name_hint(name_hint: str) -> str:
        """校验输出文件名提示词参数。"""
        text = str(name_hint or "").strip()
        if not text:
            raise ValidationError("nameHint 不能为空")
        return text

    @staticmethod
    def _normalize_file_suffix(suffix: str) -> str:
        """将文件后缀归一化为工具内部格式。"""
        text = str(suffix or "").strip().lower()
        if text in JPEG_SUFFIX_ALIASES:
            text = JPEG_SUFFIX_ALIASES[text]
        if text not in SUPPORTED_OUTPUT_FORMATS:
            raise ValidationError(f"文件后缀仅支持: {', '.join(sorted(SUPPORTED_FILE_SUFFIXES))}")
        return text

    @classmethod
    def _extract_required_suffix_from_file_name(cls, file_name: str) -> str:
        """从文件名中提取并校验后缀。"""
        name = str(file_name or "").strip()
        if "." not in name:
            raise ValidationError("文件名必须带图片后缀（png/jpeg/jpg/webp）")
        suffix = name.rsplit(".", 1)[-1]
        return cls._normalize_file_suffix(suffix)

    @staticmethod
    def _normalize_aspect_ratio(aspect_ratio: str | None) -> str:
        """校验比例参数。"""
        text = str(aspect_ratio or DEFAULT_ASPECT_RATIO).strip().lower()
        if text in SUPPORTED_ASPECT_RATIOS:
            return text
        if ASPECT_RATIO_PATTERN.fullmatch(text):
            return text
        raise ValidationError("aspectRatio 仅支持 auto 或类似 1:1、16:9 的比例格式")

    @staticmethod
    def _normalize_resolution(resolution: str | None) -> str:
        """校验分辨率档位参数。"""
        text = str(resolution or DEFAULT_RESOLUTION).strip().upper()
        if text not in SUPPORTED_RESOLUTIONS:
            raise ValidationError(f"resolution 仅支持: {', '.join(sorted(SUPPORTED_RESOLUTIONS))}")
        return text

    @staticmethod
    def _normalize_file_name(file_name: str | None, *, required_suffix: str) -> str:
        """校验并生成图片文件名。"""
        normalized_required_suffix = ImageToolService._normalize_file_suffix(required_suffix)
        raw = str(file_name or "").strip()
        if not raw:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            random_suffix = uuid4().hex[:8]
            return f"nanobanana_{stamp}_{random_suffix}.{normalized_required_suffix}"

        if "/" in raw or "\\" in raw:
            raise ValidationError("file_name 必须是文件名，不能包含路径")
        if raw in {".", ".."}:
            raise ValidationError("file_name 非法")

        candidate = Path(raw).name
        current_suffix = candidate.rsplit(".", 1)[-1].lower() if "." in candidate else ""
        if not current_suffix:
            candidate = f"{candidate}.{normalized_required_suffix}"
            current_suffix = normalized_required_suffix
        normalized_current_suffix = ImageToolService._normalize_file_suffix(current_suffix)
        if normalized_current_suffix != normalized_required_suffix:
            raise ValidationError(f"file_name 后缀需与 output_format 一致（.{normalized_required_suffix}）")
        if len(candidate) > 128:
            raise ValidationError("file_name 过长（最多 128 个字符）")
        return candidate

    @staticmethod
    def _file_stem_from_name_hint(name_hint: str) -> str:
        """根据 nameHint 生成安全文件名前缀。"""
        normalized = str(name_hint or "").strip()
        # Windows 非法文件名字符替换为下划线，空白折叠。
        normalized = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", normalized)
        normalized = re.sub(r"\s+", "_", normalized)
        normalized = normalized.strip(" ._")
        if not normalized:
            normalized = "image"
        return normalized[:48]

    @classmethod
    def _generate_workspace_file_name(cls, name_hint: str) -> str:
        """基于 nameHint 生成唯一文件名（固定 png）。"""
        stem = cls._file_stem_from_name_hint(name_hint)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        random_suffix = uuid4().hex[:8]
        return cls._normalize_file_name(
            f"{stem}_{stamp}_{random_suffix}.{DEFAULT_OUTPUT_FORMAT}",
            required_suffix=DEFAULT_OUTPUT_FORMAT,
        )

    @staticmethod
    def _normalize_image_paths(image_paths: object | None) -> list[str]:
        """规范化参考图路径数组（可空）。"""
        if image_paths is None:
            return []
        if isinstance(image_paths, str):
            text = image_paths.strip()
            return [text] if text else []
        if not isinstance(image_paths, (list, tuple)):
            raise ValidationError("imagePath 必须是字符串数组")
        normalized: list[str] = []
        for item in image_paths:
            path = str(item or "").strip()
            if not path:
                continue
            normalized.append(path)
        if len(normalized) > MAX_IMAGE_PATHS:
            raise ValidationError(f"imagePath 最多支持 {MAX_IMAGE_PATHS} 项")
        return normalized

    @staticmethod
    def _assert_llm_config(llm_config: LLMConfig | None) -> LLMConfig:
        """确保图片工具具备可用的 LLM 接入配置。"""
        if llm_config is None:
            raise ValidationError("image_gen_edit 需要 llm_config")
        if not str(llm_config.api_key or "").strip():
            raise ValidationError("image_gen_edit 需要可用的 api_key")
        return llm_config

    async def generate_image_to_workspace(
        self,
        *,
        user_id: str,
        employee_id: str,
        llm_config: LLMConfig | None,
        name_hint: str,
        image_paths: object | None,
        prompt: str,
        aspect_ratio: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, object]:
        """生成单张图片并保存到员工 ``/workspace`` 目录。"""
        effective_llm_config = self._assert_llm_config(llm_config)
        normalized_name_hint = self._normalize_name_hint(name_hint)
        normalized_image_paths = self._normalize_image_paths(image_paths)
        normalized_prompt = self._normalize_prompt(prompt)
        normalized_aspect_ratio = self._normalize_aspect_ratio(aspect_ratio)
        normalized_resolution = self._normalize_resolution(resolution)
        normalized_file_name = self._generate_workspace_file_name(normalized_name_hint)

        normalized_base_url = normalize_openai_base_url(effective_llm_config.base_url)
        endpoint = f"{normalized_base_url.rstrip('/')}/images/generations"
        client = AsyncOpenAI(
            api_key=effective_llm_config.api_key,
            base_url=normalized_base_url,
            timeout=120.0,
        )
        try:
            try:
                response = await client.images.generate(
                    model=IMAGE_GEN_MODEL,
                    prompt=normalized_prompt,
                    response_format="b64_json",
                    n=1,
                    extra_body={
                        "nameHint": normalized_name_hint,
                        "imagePath": normalized_image_paths,
                        "aspectRatio": normalized_aspect_ratio,
                        "resolution": normalized_resolution,
                    },
                )
            except APIStatusError as exc:
                raise RuntimeError(f"图片生成接口调用失败（HTTP {exc.status_code}）：{exc}") from exc
            except APITimeoutError as exc:
                raise RuntimeError(f"图片生成接口连接超时：{exc}") from exc
            except APIConnectionError as exc:
                raise RuntimeError(f"图片生成接口连接失败：{exc}") from exc
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"图片生成接口调用异常：{exc}") from exc
        finally:
            await client.close()

        data_items = list(getattr(response, "data", None) or [])
        if not data_items:
            raise RuntimeError("图片生成接口未返回 data")
        first_item = data_items[0]
        encoded_image = str(getattr(first_item, "b64_json", "") or "").strip()
        if not encoded_image:
            raise RuntimeError("图片生成接口未返回 b64_json")

        try:
            image_bytes = base64.b64decode(encoded_image, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"图片 base64 解码失败：{exc}") from exc

        workspace_dir = user_employee_workspace_dir(user_id, employee_id).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        target_path = (workspace_dir / normalized_file_name).resolve()
        _ensure_inside(workspace_dir, target_path, error_message="workspace 目标文件路径非法")
        async with aiofiles.open(target_path, "wb") as output_file:
            await output_file.write(image_bytes)

        revised_prompt = str(getattr(first_item, "revised_prompt", "") or "")
        return {
            "model": IMAGE_GEN_MODEL,
            "endpoint": endpoint,
            "name_hint": normalized_name_hint,
            "image_paths": normalized_image_paths,
            "workspace_file_name": normalized_file_name,
            "workspace_relative_path": f"/employee/workspace/{normalized_file_name}",
            "workspace_abs_path": str(target_path),
            "aspect_ratio": normalized_aspect_ratio,
            "resolution": normalized_resolution,
            "output_format": DEFAULT_OUTPUT_FORMAT,
            "bytes": len(image_bytes),
            "revised_prompt": revised_prompt,
        }

    def copy_workspace_image_to_brand_library(
        self,
        *,
        user_id: str,
        employee_id: str,
        workspace_file_name: str,
        brand_file_name: str | None = None,
    ) -> dict[str, str]:
        """将员工 ``/workspace`` 下图片复制到用户 ``/brand_library``。"""
        raw_workspace_file_name = str(workspace_file_name or "").strip()
        if not raw_workspace_file_name:
            raise ValidationError("workspace_file_name 不能为空")
        source_suffix = self._extract_required_suffix_from_file_name(raw_workspace_file_name)
        normalized_workspace_file_name = self._normalize_file_name(
            raw_workspace_file_name,
            required_suffix=source_suffix,
        )

        workspace_dir = user_employee_workspace_dir(user_id, employee_id).resolve()
        source_path = (workspace_dir / normalized_workspace_file_name).resolve()
        _ensure_inside(workspace_dir, source_path, error_message="workspace 源文件路径非法")
        if not source_path.exists() or not source_path.is_file():
            raise NotFoundError(f"workspace 文件不存在：{normalized_workspace_file_name}")

        extension = self._extract_required_suffix_from_file_name(normalized_workspace_file_name)
        raw_brand_file_name = str(brand_file_name or "").strip()
        if not raw_brand_file_name:
            normalized_brand_file_name = normalized_workspace_file_name
        else:
            normalized_brand_file_name = self._normalize_file_name(
                raw_brand_file_name,
                required_suffix=extension,
            )

        brand_library_dir = user_brand_library_dir(user_id).resolve()
        brand_library_dir.mkdir(parents=True, exist_ok=True)
        target_path = (brand_library_dir / normalized_brand_file_name).resolve()
        _ensure_inside(brand_library_dir, target_path, error_message="brand_library 目标文件路径非法")
        shutil.copy2(source_path, target_path)

        return {
            "workspace_file_name": normalized_workspace_file_name,
            "workspace_relative_path": f"/employee/workspace/{normalized_workspace_file_name}",
            "brand_file_name": normalized_brand_file_name,
            "brand_relative_path": f"/brand_library/{normalized_brand_file_name}",
            "brand_abs_path": str(target_path),
        }
