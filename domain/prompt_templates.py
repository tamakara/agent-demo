"""提示词文件加载与模板注入。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
    """读取指定提示词文件内容。"""
    return path.read_text(encoding="utf-8")


def _read_template_file(file_name: str) -> str:
    """读取 templates 子目录下的模板文件。"""
    return _read_prompt_file(PROMPT_TEMPLATES_DIR / file_name)


def _read_section_file(file_name: str) -> str:
    """读取 sections 子目录下的片段文件。"""
    return _read_prompt_file(PROMPT_SECTIONS_DIR / file_name)


def render_prompt_template(template: str, variables: Mapping[str, str]) -> str:
    """将变量注入模板占位符。"""
    rendered = str(template or "")
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered.strip()


def compose_chat_system_prompt(
    *,
    window_preamble: str,
    tool_definitions: str,
    memory_core: str,
    memory_persona: str,
    memory_schedule: str,
    memory_workbook: str,
) -> str:
    """构建数字员工聊天场景的 system 提示词。"""
    tools_prompt = render_prompt_template(
        _read_section_file(TOOLS_BASE_PROMPT_FILE),
        {
            "TOOL_DEFINITIONS": str(tool_definitions or "").strip(),
        },
    ).strip()
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
            "SOUL_NOTEBOOK_PROMPT": str(memory_persona or "").strip(),
            "SCHEDULE_NOTEBOOK_PROMPT": str(memory_schedule or "").strip(),
            "WORKBOOK_NOTEBOOK_PROMPT": str(memory_workbook or "").strip(),
            "MEMORY_PROMPT": str(memory_core or "").strip(),
        },
    )


def compose_compression_system_prompt(*, resident_base_system: str) -> str:
    """构建压缩归档场景的 system 提示词。"""
    return render_prompt_template(
        _read_template_file(COMPRESSION_TEMPLATE_FILE),
        {
            "BASE_PROMPT": str(resident_base_system or "").strip(),
            "ARCHIVE_TASK_PROMPT": _read_section_file(COMPRESSION_BASE_PROMPT_FILE).strip(),
        },
    )


def compose_image_generation_prompt(*, user_prompt: str) -> str:
    """构建画图模型调用场景的 prompt。"""
    return render_prompt_template(
        _read_template_file(IMAGE_GENERATION_TEMPLATE_FILE),
        {
            "BASE_PROMPT": _read_section_file(IMAGE_GENERATION_BASE_PROMPT_FILE).strip(),
            "USER_PROMPT": str(user_prompt or "").strip(),
        },
    )

