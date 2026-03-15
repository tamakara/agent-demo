"""用户与员工模块路由。"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.dependencies import AppContainer
from api.requests import EmployeeCreateRequest, SettingsUpdateRequest
from api.routes_shared import FIXED_MAX_TOOL_ROUNDS, normalize_employee_path, normalize_user_path, raise_http
from api.routes_shared import new_request_id, resolve_employee
from common.errors import AppError
from common.response import success_response


def create_user_router(container: AppContainer) -> APIRouter:
    """创建用户与员工相关路由。"""
    router = APIRouter(tags=["user"])

    @router.get("/user/employees")
    async def list_employees(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """查询用户下的数字员工列表。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            data = {"employees": [asdict(item) for item in employees]}
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/user/employees")
    async def create_employee(body: EmployeeCreateRequest) -> JSONResponse:
        """创建新数字员工。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(body.user_id)
            entry = await container.employee_service.create_employee(normalized_user_id)
            await container.memory_file_service.ensure_employee_files(normalized_user_id, entry.employee_id)
            return JSONResponse(success_response(request_id=request_id, data={"created": True, "employee": asdict(entry)}))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.post("/user/employees/{employee_id}/reset")
    async def reset_employee(
        employee_id: str,
        user_id: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """重置指定数字员工（删除后同编号重建）。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            normalized_employee_id = normalize_employee_path(employee_id, default="1")
            recreated = await container.employee_service.reset_employee(
                normalized_user_id,
                normalized_employee_id,
            )
            await container.memory_file_service.delete_employee_data(
                normalized_user_id,
                normalized_employee_id,
            )
            await container.memory_file_service.ensure_employee_files(
                normalized_user_id,
                normalized_employee_id,
            )
            files = await container.memory_file_service.list_files(
                normalized_user_id,
                normalized_employee_id,
            )
            employees = await container.employee_service.list_employees(normalized_user_id, limit=300)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "ok": True,
                        "employee": asdict(recreated),
                        "employees": [asdict(item) for item in employees],
                        "files": [asdict(item) for item in files],
                        "tree": container.memory_file_service.list_data_paths(
                            normalized_user_id,
                            normalized_employee_id,
                        ),
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.delete("/user/employees/{employee_id}")
    async def delete_employee(
        employee_id: str,
        user_id: str = Query(..., min_length=1),
    ) -> JSONResponse:
        """删除指定数字员工。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            normalized_employee_id = normalize_employee_path(employee_id, default="1")
            deleted = await container.employee_service.delete_employee(
                normalized_user_id,
                normalized_employee_id,
            )
            await container.memory_file_service.delete_employee_data(
                normalized_user_id,
                normalized_employee_id,
            )
            remaining = await container.employee_service.list_employees(normalized_user_id, limit=300)
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "deleted": True,
                        "employee": asdict(deleted),
                        "employees": [asdict(item) for item in remaining],
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/user/employee-messages")
    async def get_employee_messages(
        user_id: str = Query(..., min_length=1),
        employee_id: str = Query(default="1", min_length=1),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        """查询指定数字员工的历史消息。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            normalized_employee_id, session_id = await resolve_employee(
                container,
                user_id=normalized_user_id,
                employee_id=employee_id,
                auto_create_default=True,
            )
            messages = await container.employee_service.list_employee_messages(
                normalized_user_id,
                normalized_employee_id,
                limit=limit,
            )
            return JSONResponse(
                success_response(
                    request_id=request_id,
                    data={
                        "user_id": normalized_user_id,
                        "employee_id": normalized_employee_id,
                        "session_id": session_id,
                        "messages": [asdict(item) for item in messages],
                    },
                )
            )
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.get("/user/settings")
    async def get_settings(user_id: str = Query(..., min_length=1)) -> JSONResponse:
        """读取用户模型配置。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(user_id)
            settings = await container.settings_service.get_settings(normalized_user_id)
            data = {
                "model": settings.model,
                "api_key": settings.api_key,
                "base_url": settings.base_url,
                "max_tool_rounds": FIXED_MAX_TOOL_ROUNDS,
                "total_token_limit": settings.total_token_limit,
                "tokenizer_model": settings.tokenizer_model,
            }
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    @router.put("/user/settings")
    async def update_settings(body: SettingsUpdateRequest) -> JSONResponse:
        """更新用户模型配置。"""
        request_id = new_request_id()
        try:
            normalized_user_id = normalize_user_path(body.user_id)
            latest = await container.settings_service.update_settings(
                user_id=normalized_user_id,
                model=body.model,
                api_key=body.api_key,
                base_url=body.base_url,
                total_token_limit=body.total_token_limit,
                tokenizer_model=body.tokenizer_model,
            )
            data = {
                "model": latest.model,
                "api_key": latest.api_key,
                "base_url": latest.base_url,
                "max_tool_rounds": FIXED_MAX_TOOL_ROUNDS,
                "total_token_limit": latest.total_token_limit,
                "tokenizer_model": latest.tokenizer_model,
            }
            return JSONResponse(success_response(request_id=request_id, data=data))
        except AppError as exc:
            raise raise_http(exc, request_id) from exc

    return router

