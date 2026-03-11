"""记忆文件服务：封装文件初始化、读取与写入操作。"""

from __future__ import annotations

from app.ports.repositories import MemoryFileRepositoryPort
from domain.models import MemoryFileEntry


class MemoryFileService:
    """记忆文件读写服务。"""
    def __init__(self, memory_repo: MemoryFileRepositoryPort) -> None:
        """注入记忆文件仓储。"""
        self.memory_repo = memory_repo

    async def ensure_user_files(self, user_id: str) -> None:
        """确保用户记忆目录及默认文件已就绪。"""
        await self.memory_repo.ensure_memory_files_exist(user_id)

    async def list_files(self, user_id: str) -> list[MemoryFileEntry]:
        """读取并返回用户全部记忆文件。"""
        files: list[MemoryFileEntry] = []
        for file_name in self.memory_repo.list_memory_file_names(user_id):
            try:
                content = await self.memory_repo.read_memory_file(user_id=user_id, file_name=file_name)
            except Exception:
                # 某个文件读失败时不阻断整体列表返回。
                content = ""
            files.append(MemoryFileEntry(file_name=file_name, content=content))
        return files

    async def reset_files(self, user_id: str) -> tuple[list[str], list[MemoryFileEntry]]:
        """重置记忆文件并返回恢复文件名及最新文件列表。"""
        restored = await self.memory_repo.reset_memory_to_initial_content(user_id)
        files = await self.list_files(user_id)
        return restored, files

    async def update_file(self, *, user_id: str, file_name: str, content: str, mode: str) -> str:
        """更新指定文件并返回写入后的最新内容。"""
        await self.memory_repo.write_memory_file(
            user_id=user_id,
            file_name=file_name,
            content=content,
            mode=mode,
            allow_system_prompt=True,
        )
        return await self.memory_repo.read_memory_file(user_id=user_id, file_name=file_name)

