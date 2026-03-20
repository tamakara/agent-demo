"""Prompt template repository reading files from prompts/ resources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.interfaces import IPromptTemplateRepository


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_TEMPLATES_DIR = PROMPTS_DIR / "templates"
PROMPT_SECTIONS_DIR = PROMPTS_DIR / "sections"

CHAT_TEMPLATE_FILE = "chat.xml"
COMPRESSION_TEMPLATE_FILE = "compression.xml"
IMAGE_GENERATION_TEMPLATE_FILE = "image_generation.xml"

CHAT_BASE_PROMPT_FILE = "chat_base_prompt.md"
TOOLS_BASE_PROMPT_FILE = "tools_base_prompt.md"
COMPRESSION_BASE_PROMPT_FILE = "compression_base_prompt.md"
IMAGE_GENERATION_BASE_PROMPT_FILE = "image_generation_base_prompt.md"


def _read_prompt_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_template_file(file_name: str) -> str:
    return _read_prompt_file(PROMPT_TEMPLATES_DIR / file_name)


def _read_section_file(file_name: str) -> str:
    return _read_prompt_file(PROMPT_SECTIONS_DIR / file_name)


def render_prompt_template(template: str, variables: Mapping[str, str]) -> str:
    rendered = str(template or "")
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered.strip()


def compose_tools_prompt(*, tool_definitions: str) -> str:
    return render_prompt_template(
        _read_section_file(TOOLS_BASE_PROMPT_FILE),
        {
            "TOOL_DEFINITIONS": str(tool_definitions or "").strip(),
        },
    ).strip()


class FilePromptTemplateRepository(IPromptTemplateRepository):
    def compose_chat_system_prompt(
        self,
        *,
        window_preamble: str,
        tool_definitions: str,
        memory_core: str,
        memory_file: str,
        memory_persona: str,
        memory_schedule: str,
        memory_workbook: str,
    ) -> str:
        tools_prompt = compose_tools_prompt(tool_definitions=tool_definitions)
        base_prompt = "\n\n".join(
            part
            for part in (
                str(window_preamble or "").strip(),
                _read_section_file(CHAT_BASE_PROMPT_FILE).strip(),
            )
            if part
        ).strip()

        return render_prompt_template(
            _read_template_file(CHAT_TEMPLATE_FILE),
            {
                "BASE_PROMPT": base_prompt,
                "TOOLS_PROMPT": str(tools_prompt or "").strip(),
                "FILE_NOTEBOOK_PROMPT": str(memory_file or "").strip(),
                "SOUL_NOTEBOOK_PROMPT": str(memory_persona or "").strip(),
                "SCHEDULE_NOTEBOOK_PROMPT": str(memory_schedule or "").strip(),
                "WORKBOOK_NOTEBOOK_PROMPT": str(memory_workbook or "").strip(),
                "MEMORY_PROMPT": str(memory_core or "").strip(),
            },
        )

    def compose_compression_system_prompt(
        self,
        *,
        tool_definitions: str,
        memory_file_path: str,
        memory_token_limit: int,
    ) -> str:
        tools_prompt = compose_tools_prompt(tool_definitions=tool_definitions)
        normalized_limit = max(1, int(memory_token_limit))
        base_prompt = render_prompt_template(
            _read_section_file(COMPRESSION_BASE_PROMPT_FILE).strip(),
            {
                "MEMORY_FILE_PATH": str(memory_file_path or ".memory/memory.md").strip(),
                "MEMORY_TOKEN_LIMIT": str(normalized_limit),
            },
        )
        return render_prompt_template(
            _read_template_file(COMPRESSION_TEMPLATE_FILE),
            {
                "BASE_PROMPT": base_prompt,
                "TOOLS_PROMPT": str(tools_prompt or "").strip(),
            },
        )

    def compose_image_generation_prompt(self, *, user_prompt: str) -> str:
        return render_prompt_template(
            _read_template_file(IMAGE_GENERATION_TEMPLATE_FILE),
            {
                "BASE_PROMPT": _read_section_file(IMAGE_GENERATION_BASE_PROMPT_FILE).strip(),
                "USER_PROMPT": str(user_prompt or "").strip(),
            },
        )
