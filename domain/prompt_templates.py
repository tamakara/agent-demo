"""提示词文件加载与模板注入。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_TEMPLATES_DIR = PROMPTS_DIR / "templates"
PROMPT_SECTIONS_DIR = PROMPTS_DIR / "sections"

CHAT_SYSTEM_TEMPLATE_FILE = "chat_system.md"
FLUSH_ARCHIVE_SYSTEM_TEMPLATE_FILE = "flush_archive_system.md"
IMAGE_GENERATION_TEMPLATE_FILE = "image_generation.md"

CHAT_SYSTEM_BASE_FILE = "chat_system_base.md"
TOOL_CALLING_FILE = "tool_calling.md"
IMAGE_TOOL_CALLING_FILE = "image_tool_calling.md"
FLUSH_ARCHIVE_FILE = "flush_archive.md"
IMAGE_GENERATION_BASE_FILE = "image_generation_base.md"


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
    memory_others: str,
) -> str:
    """构建数字员工聊天场景的 system 提示词。"""
    return render_prompt_template(
        _read_template_file(CHAT_SYSTEM_TEMPLATE_FILE),
        {
            "WINDOW_PREAMBLE": str(window_preamble or "").strip(),
            "BASE_SYSTEM_PROMPT": _read_section_file(CHAT_SYSTEM_BASE_FILE).strip(),
            "TOOL_CALLING_PROMPT": _read_section_file(TOOL_CALLING_FILE).strip(),
            "IMAGE_TOOL_CALLING_PROMPT": _read_section_file(IMAGE_TOOL_CALLING_FILE).strip(),
            "TOOL_DEFINITIONS": str(tool_definitions or "").strip(),
            "MEMORY_CORE": str(memory_core or "").strip(),
            "MEMORY_PERSONA": str(memory_persona or "").strip(),
            "MEMORY_SCHEDULE": str(memory_schedule or "").strip(),
            "MEMORY_WORKBOOK": str(memory_workbook or "").strip(),
            "MEMORY_OTHERS": str(memory_others or "").strip(),
        },
    )


def compose_flush_archive_system_prompt(*, resident_base_system: str) -> str:
    """构建刷盘归档场景的 system 提示词。"""
    return render_prompt_template(
        _read_template_file(FLUSH_ARCHIVE_SYSTEM_TEMPLATE_FILE),
        {
            "BASE_SYSTEM_PROMPT": str(resident_base_system or "").strip(),
            "FLUSH_ARCHIVE_PROMPT": _read_section_file(FLUSH_ARCHIVE_FILE).strip(),
        },
    )


def compose_image_generation_prompt(*, user_prompt: str) -> str:
    """构建画图模型调用场景的 prompt。"""
    return render_prompt_template(
        _read_template_file(IMAGE_GENERATION_TEMPLATE_FILE),
        {
            "IMAGE_PROMPT_BASE": _read_section_file(IMAGE_GENERATION_BASE_FILE).strip(),
            "USER_PROMPT": str(user_prompt or "").strip(),
        },
    )
