"""PromptComposer 注入式工具定义测试。"""

from __future__ import annotations

import asyncio
import unittest

from domain.prompt_composer import PromptComposer
from domain.window_policy import WindowThresholds


class PromptComposerTestCase(unittest.TestCase):
    """验证 PromptComposer 使用注入 tool schema。"""

    def test_compose_resident_system_text_uses_injected_tool_schemas(self) -> None:
        composer = PromptComposer(
            count_tokens=lambda text, _model: len(text),
            truncate_text_to_tokens=lambda text, limit, _model: text[:limit],
        )

        async def run_compose() -> str:
            return await composer.compose_resident_system_text(
                user_id="alice",
                employee_id="1",
                session={"workbench_summary": "summary"},
                model="kimi-k2.5",
                thresholds=WindowThresholds.from_total_limit(20000),
                list_memory_files=lambda _uid, _eid: ["memory.md"],
                read_memory_file=lambda **_kwargs: "memory content",
                tool_schemas=[
                    {
                        "type": "function",
                        "function": {
                            "name": "demo_tool",
                            "description": "desc",
                            "parameters": {"type": "object", "required": ["x"]},
                        },
                    }
                ],
            )

        text = asyncio.run(run_compose())
        self.assertIn("demo_tool", text)


if __name__ == "__main__":
    unittest.main()

