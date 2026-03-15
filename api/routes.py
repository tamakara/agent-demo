"""API 路由装配入口。"""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies import AppContainer
from api.routes_chat import create_chat_router
from api.routes_storage import create_storage_router
from api.routes_user import create_user_router


def create_router(container: AppContainer) -> APIRouter:
    """装配 ``chat`` / ``user`` / ``storage`` 三大模块路由。"""
    router = APIRouter()
    router.include_router(create_user_router(container))
    router.include_router(create_chat_router(container))
    router.include_router(create_storage_router(container))
    return router

