"""Prompt template repository reading files from prompts/ resources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.interfaces import IPromptTemplateRepository


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_TEMPLATES_DIR = PROMPTS_DIR / "templates"
PROMPT_SECTIONS_DIR = PROMPTS_DIR / "sections"
PROMPT_TOOLS_DIR = PROMPTS_DIR / "tools"

CHAT_TEMPLATE_FILE = "chat.xml"
COMPRESSION_TEMPLATE_FILE = "compression.xml"
IMAGE_GENERATION_TEMPLATE_FILE = "image_generation.xml"
DIALOGUE_SUMMARY_TEMPLATE_FILE = "dialogue_summary.xml"

CHAT_BASE_PROMPT_FILE = "chat_base_prompt.md"
TOOLS_BASE_PROMPT_FILE = "tools_base_prompt.md"
COMPRESSION_BASE_PROMPT_FILE = "compression_base_prompt.md"
IMAGE_GENERATION_BASE_PROMPT_FILE = "image_generation_base_prompt.md"
DIALOGUE_SUMMARY_BASE_PROMPT_FILE = "dialogue_summary_base_prompt.md"


def _read_prompt_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_template_file(file_name: str) -> str:
    return _read_prompt_file(PROMPT_TEMPLATES_DIR / file_name)


def _read_section_file(file_name: str) -> str:
    return _read_prompt_file(PROMPT_SECTIONS_DIR / file_name)


def _read_tool_prompt_file(tool_name: str) -> str:
    normalized_name = str(tool_name or "").strip()
    if not normalized_name:
        return ""
    file_path = PROMPT_TOOLS_DIR / f"{normalized_name}.md"
    if not file_path.exists():
        return ""
    return _read_prompt_file(file_path)


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
    def compose_tool_definitions(self, *, tool_names: list[str]) -> str:
        sections: list[str] = []
        seen: set[str] = set()
        for name in tool_names:
            normalized = str(name or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            section = _read_tool_prompt_file(normalized).strip()
            if section:
                sections.append(section)
            else:
                sections.append(f"- `{normalized}`")
        return "\n\n".join(sections).strip()

    def compose_chat_system_prompt(
        self,
        *,
        tool_definitions: str,
        memory_core: str,
        memory_file: str,
        memory_persona: str,
        memory_schedule: str,
        memory_workbook: str,
        workbench_summary: str,
    ) -> str:
        tools_prompt = compose_tools_prompt(tool_definitions=tool_definitions)
        base_prompt = _read_section_file(CHAT_BASE_PROMPT_FILE).strip()

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
                "WORKBENCH_SUMMARY_PROMPT": str(workbench_summary or "").strip(),
            },
        )

    def compose_compression_system_prompt(
        self,
        *,
        previous_memory: str,
        memory_token_limit: int,
    ) -> str:
        normalized_limit = max(1, int(memory_token_limit))
        base_prompt = _read_section_file(COMPRESSION_BASE_PROMPT_FILE).strip()
        return render_prompt_template(
            _read_template_file(COMPRESSION_TEMPLATE_FILE),
            {
                "BASE_PROMPT": base_prompt,
                "PREVIOUS_MEMORY": str(previous_memory or "").strip() or "(暂无内容)",
                "MEMORY_TOKEN_LIMIT": str(normalized_limit),
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

    def compose_dialogue_summary_system_prompt(
        self,
        *,
        summary_token_limit: int,
    ) -> str:
        normalized_limit = max(1, int(summary_token_limit))
        return render_prompt_template(
            _read_template_file(DIALOGUE_SUMMARY_TEMPLATE_FILE),
            {
                "BASE_PROMPT": _read_section_file(DIALOGUE_SUMMARY_BASE_PROMPT_FILE).strip(),
                "SUMMARY_TOKEN_LIMIT": str(normalized_limit),
            },
        )
