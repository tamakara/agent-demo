import unittest

from app.prompt_composer import PromptComposer
from app.window_policy import WindowThresholds


class _TemplateRepoStub:
    def __init__(self) -> None:
        self.last_workbench_summary = ""

    def compose_tool_definitions(self, *, tool_names: list[str]) -> str:  # noqa: ARG002
        return ""

    def compose_chat_system_prompt(
        self,
        *,
        tool_definitions: str,  # noqa: ARG002
        memory_core: str,  # noqa: ARG002
        memory_file: str,  # noqa: ARG002
        memory_persona: str,  # noqa: ARG002
        memory_schedule: str,  # noqa: ARG002
        memory_workbook: str,  # noqa: ARG002
        workbench_summary: str,
    ) -> str:
        self.last_workbench_summary = workbench_summary
        return workbench_summary

    def compose_compression_system_prompt(self, *, previous_memory: str, memory_token_limit: int) -> str:  # noqa: ARG002
        return ""

    def compose_dialogue_summary_system_prompt(self, *, summary_token_limit: int) -> str:  # noqa: ARG002
        return ""

    def compose_image_generation_prompt(self, *, user_prompt: str) -> str:  # noqa: ARG002
        return ""


class PromptComposerTests(unittest.IsolatedAsyncioTestCase):
    async def test_workbench_summary_is_clipped_before_template_injection(self) -> None:
        template_repo = _TemplateRepoStub()
        composer = PromptComposer(
            count_tokens=lambda text, model: len(str(text).split()),  # noqa: ARG005
            truncate_text_to_tokens=lambda text, limit, model: " ".join(str(text).split()[:limit]),  # noqa: ARG005
            template_repository=template_repo,
        )
        thresholds = WindowThresholds.from_total_limit(
            1_000,
            memory_capacity_ratio=0.10,
            notebook_capacity_ratio=0.04,
            dialogue_summary_ratio=0.05,
            retention_ratio=0.10,
        )
        summary_source = " ".join(f"word{i}" for i in range(1, 1501))

        async def _read_memory_file(**kwargs) -> str:  # noqa: ANN003, ARG001
            return ""

        await composer.compose_resident_system_text(
            user_id="u1",
            employee_id="1",
            workbench_summary=summary_source,
            model="kimi-k2.5",
            thresholds=thresholds,
            read_memory_file=_read_memory_file,
            tool_schemas=[],
        )

        injected_words = template_repo.last_workbench_summary.split()
        self.assertEqual(len(injected_words), thresholds.summary_token_limit)
        self.assertEqual(injected_words[0], "word1")
        self.assertEqual(injected_words[-1], f"word{thresholds.summary_token_limit}")


if __name__ == "__main__":
    unittest.main()
