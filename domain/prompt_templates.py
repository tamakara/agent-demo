"""底层提示词模板读取器。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

CHAT_SYSTEM_TEMPLATE_FILE = "chat_system_template.md"
CHAT_SYSTEM_BASE_FILE = "chat_system_base.md"
TOOL_CALLING_FILE = "tool_calling.md"
FLUSH_ARCHIVE_FILE = "flush_archive.md"

DEFAULT_CHAT_SYSTEM_TEMPLATE = (
    "{{WINDOW_PREAMBLE}}\n\n"
    "## 底层系统提示词\n"
    "{{BASE_SYSTEM_PROMPT}}\n\n"
    "## 工具调用提示词\n"
    "{{TOOL_CALLING_PROMPT}}\n\n"
    "## 可用工具清单（只读）\n"
    "{{TOOL_DEFINITIONS}}\n\n"
    "## 记忆：memory.md\n"
    "{{MEMORY_CORE}}\n\n"
    "## 记忆：soul.md\n"
    "{{MEMORY_PERSONA}}\n\n"
    "## 记忆：schedule.md\n"
    "{{MEMORY_SCHEDULE}}\n\n"
    "## 记忆：workbook.md\n"
    "{{MEMORY_WORKBOOK}}\n\n"
    "## 其他记忆文件\n"
    "{{MEMORY_OTHERS}}"
)

DEFAULT_CHAT_SYSTEM_BASE_PROMPT = (
    "你是一个专业、严谨、可靠的数字员工。\n"
    "- 优先理解并执行用户明确目标。\n"
    "- 回答要准确、可执行，必要时给出清晰步骤。\n"
    "- 在信息不足时先澄清关键缺口，避免臆断。"
)

DEFAULT_TOOL_CALLING_PROMPT = (
    "你可以按需调用工具来读取/写入记忆、获取时间、生成图片。\n"
    "- 有明确工具收益时再调用，避免无意义调用。\n"
    "- 严格使用工具参数约束，失败时先解释原因再重试。\n"
    "- 工具结果应先验证再纳入最终回答。"
)

DEFAULT_FLUSH_ARCHIVE_PROMPT = (
    "你是一个记忆整理专员。请分析给定对话记录，并在必要时调用 "
    "`write_memory_file` 工具，将新设定追加到最合适的记忆文件中。"
    "整理完成后，请输出纯文本“工作台摘要”，用于后续常驻区快速加载。"
)


def _read_prompt_file(file_name: str, fallback: str) -> str:
    """读取提示词文件；缺失或空内容时返回兜底文本。"""
    path = PROMPTS_DIR / file_name
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return fallback
    normalized = str(content or "").strip()
    return normalized or fallback


def load_chat_system_base_prompt() -> str:
    """加载聊天底层系统提示词。"""
    return _read_prompt_file(CHAT_SYSTEM_BASE_FILE, DEFAULT_CHAT_SYSTEM_BASE_PROMPT)


def load_chat_system_template_prompt() -> str:
    """加载聊天 system 模板提示词。"""
    return _read_prompt_file(CHAT_SYSTEM_TEMPLATE_FILE, DEFAULT_CHAT_SYSTEM_TEMPLATE)


def load_tool_calling_prompt() -> str:
    """加载工具调用提示词。"""
    return _read_prompt_file(TOOL_CALLING_FILE, DEFAULT_TOOL_CALLING_PROMPT)


def load_flush_archive_prompt() -> str:
    """加载刷盘归档提示词。"""
    return _read_prompt_file(FLUSH_ARCHIVE_FILE, DEFAULT_FLUSH_ARCHIVE_PROMPT)
