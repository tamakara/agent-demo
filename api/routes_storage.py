"""持久化文件与目录模块路由。"""

from __future__ import annotations

import mimetypes
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from api.dependencies import AppContainer
from api.requests import MemoryFileUpdateRequest
from api.routes_shared import (
    DELETABLE_DATA_ROOTS,
    EDITABLE_TEXT_SUFFIXES,
    PREVIEWABLE_IMAGE_SUFFIXES,
    data_root_from_tree_path,
    deduplicate_file_name,
    new_request_id,
    normalize_upload_file_name,
    normalize_user_path,
    raise_http,
)
from common.errors import AppError, NotFoundError, ValidationError
from common.response import success_response
from infra.memory.storage_layout import user_brand_library_dir


def create_storage_router(container: AppContainer) -> APIRouter:
    """创建存储相关路由。"""
    router = APIRouter(tags=["storage"])

    @router.get("/storage/tree")
    async def storage_tree(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """列出用户级数据目录树与可编辑记忆文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            for item in employees:
                await container.memory_file_service.ensure_employee_files(normalized_user_id, item.employee_id)

            files_payload: list[dict[str, Any]] = []
            for item in employees:
                files = await container.memory_file_service.list_files(normalized_user_id, item.employee_id)
                for file_item in files:
                    serialized = asdict(file_item)
                    relative = str(serialized.get("relative_path") or "").lstrip("/")
                    serialized["employee_id"] = item.employee_id
                    serialized["relative_path"] = (
                        f"employee/{item.employee_id}/{relative}" if relative else f"employee/{item.employee_id}"
                    )
                    files_payload.append(serialized)

            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "data_dir": container.memory_file_service.data_root(normalized_user_id, "1"),
                        "tree": container.memory_file_service.list_data_paths(normalized_user_id, "1"),
                        "files": files_payload,
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/storage/file-preview")
    async def file_preview(
        user_id: str = Query(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> FileResponse:
        """预览用户目录中的图片文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            abs_path = container.memory_file_service.resolve_data_file_path(
                normalized_user_id,
                "1",
                path,
            )
            suffix = abs_path.rsplit(".", 1)[-1].lower() if "." in abs_path else ""
            normalized_suffix = f".{suffix}" if suffix else ""
            if normalized_suffix not in PREVIEWABLE_IMAGE_SUFFIXES:
                raise ValidationError(f"仅支持图片预览：{path}")
            media_type = mimetypes.guess_type(abs_path)[0] or "application/octet-stream"
            return FileResponse(path=abs_path, media_type=media_type)
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/storage/file-content")
    async def file_content(
        user_id: str = Query(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """读取目录树中的文本文件内容。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            abs_path = container.memory_file_service.resolve_data_file_path(
                normalized_user_id,
                "1",
                path,
            )
            if Path(abs_path).suffix.lower() not in EDITABLE_TEXT_SUFFIXES:
                raise ValidationError(f"仅支持文本文件读取（.md/.txt）：{path}")
            try:
                content = Path(abs_path).read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValidationError(f"文本文件编码不支持 UTF-8：{path}") from exc
            return JSONResponse(success_response(request_id=request_id, data={"path": path, "content": content}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.put("/storage/file-content")
    async def update_file_content(
        body: MemoryFileUpdateRequest,
        user_id: str = Query(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """更新目录树中的文本文件内容。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            abs_path = container.memory_file_service.resolve_data_file_path(
                normalized_user_id,
                "1",
                path,
            )
            file_path = Path(abs_path)
            if file_path.suffix.lower() not in EDITABLE_TEXT_SUFFIXES:
                raise ValidationError(f"仅支持文本文件写入（.md/.txt）：{path}")

            if body.mode == "append":
                append_text = body.content
                if append_text and not append_text.endswith("\n"):
                    append_text = f"{append_text}\n"
                with file_path.open("a", encoding="utf-8") as output_file:
                    output_file.write(append_text)
            else:
                file_path.write_text(body.content, encoding="utf-8")

            latest = file_path.read_text(encoding="utf-8")
            return JSONResponse(success_response(request_id=request_id, data={"path": path, "content": latest}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.delete("/storage/file")
    async def delete_file(
        user_id: str = Query(..., min_length=1),
        path: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """删除目录树中的单个文件。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            root_name = data_root_from_tree_path(path)
            if root_name not in DELETABLE_DATA_ROOTS:
                raise ValidationError("仅允许删除 brand_library 与 skill_library 下的文件")
            abs_path = container.memory_file_service.resolve_data_file_path(
                normalized_user_id,
                "1",
                path,
            )
            target = Path(abs_path)
            if not target.exists() or not target.is_file():
                raise NotFoundError(f"文件不存在：{path}")
            target.unlink()
            return JSONResponse(success_response(request_id=request_id, data={"deleted": True, "path": path}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/storage/brand-library/upload")
    async def upload_brand_library_files(
        files: list[UploadFile] = File(...),
        user_id: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """上传单个或多个文件到用户 ``/brand_library``。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            brand_library_dir = user_brand_library_dir(normalized_user_id).resolve()
            brand_library_dir.mkdir(parents=True, exist_ok=True)
            if not files:
                raise ValidationError("请至少选择一个文件")

            uploaded: list[dict[str, Any]] = []
            for upload in files:
                try:
                    original_name = normalize_upload_file_name(upload.filename or "")
                    original_target_path = (brand_library_dir / original_name).resolve()
                    if original_target_path != brand_library_dir and brand_library_dir not in original_target_path.parents:
                        raise ValidationError("上传文件路径非法")
                    name_conflicted = original_target_path.exists()

                    final_name = original_name
                    if name_conflicted:
                        final_name = deduplicate_file_name(brand_library_dir, original_name)

                    target_path = (brand_library_dir / final_name).resolve()
                    if target_path != brand_library_dir and brand_library_dir not in target_path.parents:
                        raise ValidationError("上传文件路径非法")
                    payload = await upload.read()
                    target_path.write_bytes(payload)
                    uploaded.append(
                        {
                            "file_name": final_name,
                            "original_file_name": original_name,
                            "renamed": final_name != original_name,
                            "path": f"/brand_library/{final_name}",
                            "size": len(payload),
                            "name_conflicted": name_conflicted,
                        }
                    )
                finally:
                    await upload.close()

            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={"uploaded": uploaded, "count": len(uploaded)},
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    return router

