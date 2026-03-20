import unittest
from typing import Any

from app.errors import NotFoundError, ValidationError
from domain.models import LLMConfig
from infra.agent.tools.builtin_tools import BuiltinToolRunner


class _TokenCounterStub:
    def count_tokens(self, text: str, model: str) -> int:  # noqa: ARG002
        return len(str(text).split())

    def truncate_text_to_tokens(self, text: str, limit: int, model: str) -> str:  # noqa: ARG002
        return " ".join(str(text).split()[:limit])


class _ClockStub:
    async def get_current_time(self) -> str:
        return "now"


class _MemoryRepoStub:
    def __init__(self) -> None:
        self.files: dict[str, str] = {
            "file.md": "alpha",
            "soul.md": "beta",
            "memory.md": "one two three",
        }

    async def read_memory_file(self, *, user_id: str, employee_id: str, file_name: str) -> str:  # noqa: ARG002
        normalized = str(file_name or "").strip()
        if normalized not in self.files:
            raise NotFoundError(f"missing: {normalized}")
        return self.files[normalized]

    async def write_notebook_file(
        self,
        *,
        user_id: str,  # noqa: ARG002
        employee_id: str,  # noqa: ARG002
        file_name: str,
        content: str,
        mode: str,
    ) -> str:
        normalized = str(file_name or "").strip()
        if mode == "overwrite":
            self.files[normalized] = str(content or "")
        else:
            previous = self.files.get(normalized, "")
            appended = str(content or "")
            if appended and not appended.endswith("\n"):
                appended = f"{appended}\n"
            self.files[normalized] = f"{previous}{appended}"
        return "ok"

    def list_memory_file_names(self, user_id: str, employee_id: str) -> list[str]:  # noqa: ARG002
        return list(self.files.keys())

    @staticmethod
    def memory_relative_path(file_name: str) -> str:
        normalized = str(file_name or "").strip()
        if not normalized.endswith(".md"):
            raise ValidationError("仅支持 .md 文件")
        if normalized == "memory.md":
            return ".memory/memory.md"
        return f"notebook/{normalized}"

    # Unused in these tests but required by runner type expectations in other paths.
    def resolve_data_file_path(self, *args: Any, **kwargs: Any) -> str:  # noqa: ANN401, ARG002
        raise NotImplementedError

    def list_employee_visible_directory(self, *args: Any, **kwargs: Any) -> dict[str, object]:  # noqa: ANN401, ARG002
        raise NotImplementedError

    def copy_library_file_to_workspace(self, *args: Any, **kwargs: Any) -> dict[str, object]:  # noqa: ANN401, ARG002
        raise NotImplementedError

    async def ensure_memory_files_exist(self, user_id: str, employee_id: str) -> None:  # noqa: ARG002
        return None


def _llm_config() -> LLMConfig:
    return LLMConfig(
        model="m",
        api_key="k",
        base_url=None,
        total_token_limit=100,
        tokenizer_model="kimi-k2.5",
        max_tool_rounds=4,
        memory_capacity_ratio=0.10,
        notebook_capacity_ratio=0.04,
        dialogue_summary_ratio=0.05,
        retention_ratio=0.10,
        deep_thinking_enabled=False,
    )


class BuiltinToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_notebook_write_uses_dynamic_equal_share_limit(self) -> None:
        runner = BuiltinToolRunner(
            memory_repo=_MemoryRepoStub(),
            clock=_ClockStub(),
            token_counter=_TokenCounterStub(),
        )
        with self.assertRaises(ValidationError) as exc:
            await runner.execute(
                "write_notebook_file",
                {"file_name": "workbook.md", "content": "one two", "mode": "overwrite"},
                user_id="u1",
                employee_id="1",
                llm_config=_llm_config(),
                allow_hidden_memory_files=False,
            )
        self.assertIn("notebook 总预算", str(exc.exception))
        self.assertIn("单文件限制 1 token", str(exc.exception))

    async def test_memory_md_uses_memory_capacity_ratio_limit(self) -> None:
        runner = BuiltinToolRunner(
            memory_repo=_MemoryRepoStub(),
            clock=_ClockStub(),
            token_counter=_TokenCounterStub(),
        )
        oversized = " ".join(["x"] * 11)
        with self.assertRaises(ValidationError) as exc:
            await runner.execute(
                "write_notebook_file",
                {"file_name": "memory.md", "content": oversized, "mode": "overwrite"},
                user_id="u1",
                employee_id="1",
                llm_config=_llm_config(),
                allow_hidden_memory_files=True,
            )
        self.assertIn("memory.md", str(exc.exception))
        self.assertIn("限制 10 token", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
