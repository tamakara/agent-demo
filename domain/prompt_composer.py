"""系统提示词与消息窗口拼装逻辑。"""

from __future__ import annotations

from typing import Any, Callable

from domain.chat.memory_files import (
    COMPRESSED_MEMORY_FILE,
    PERSONA_FILE,
    SCHEDULE_FILE,
    WORKBOOK_FILE,
)
from domain.prompt_templates import compose_chat_system_prompt
from domain.tool_protocol import normalize_prompt_role
from domain.window_policy import WindowThresholds


class PromptComposer:
    """负责生成常驻 system 内容以及消息裁剪。"""

    def __init__(
        self,
        count_tokens: Callable[[str, str], int],
        truncate_text_to_tokens: Callable[[str, int, str], str],
    ) -> None:
        """初始化实例依赖和内部状态。"""
        self._count_tokens = count_tokens
        self._truncate_text_to_tokens = truncate_text_to_tokens

    @staticmethod
    def _render_tool_definitions_from_schema(tool_schemas: list[dict[str, Any]]) -> str:
        """执行内部辅助逻辑。"""
        lines: list[str] = []
        for schema in tool_schemas:
            function_spec = schema.get("function", {})
            if not isinstance(function_spec, dict):
                continue

            name = str(function_spec.get("name", "")).strip() or "unknown_tool"
            desc = str(function_spec.get("description", "")).strip() or "无描述"
            parameters = function_spec.get("parameters", {})
            required_fields: list[str] = []
            if isinstance(parameters, dict):
                raw_required = parameters.get("required", [])
                if isinstance(raw_required, list):
                    required_fields = [str(field).strip() for field in raw_required if str(field).strip()]

            required_text = "、".join(required_fields) if required_fields else "无"
            lines.append(f"- `{name}`：{desc}（必填参数：{required_text}）")
        return "\n".join(lines).strip()

    @staticmethod
    def _system_preamble(thresholds: WindowThresholds) -> str:
        """执行内部辅助逻辑。"""
        return (
            f"你正在运行于 {thresholds.total_limit} token 上下文窗口。\n"
            f"- 固定预算 100% = 系统区 {thresholds.system_prompt_limit}（10%）"
            f" + 最近区 {thresholds.recent_total_limit}（10%=摘要 {thresholds.summary_limit}"
            f" + 原始 {thresholds.recent_raw_limit}）"
            f" + 对话区 {thresholds.dialogue_limit}（80%，工具事件计入此区）。\n"
            f"- 当非刷盘状态下总量超过 {thresholds.flush_trigger} token 会触发刷盘。\n"
            f"- 刷盘期间启用临时缓冲区：上限 {thresholds.buffer_limit} token（等于对话区 80%）；"
            "缓冲区超限时应拒绝新消息并提示稍后重试。\n"
            "- 请优先复用已有记忆，并在必要时调用工具更新记忆。"
        )

    @staticmethod
    def _normalize_memory_text(raw_text: str) -> str:
        """将记忆文本标准化为空值兜底。"""
        text = str(raw_text or "").strip()
        return text or "(暂无内容)"

    def fit_section_to_budget(
        self,
        *,
        section_title: str,
        content: str,
        token_budget: int,
        model: str,
    ) -> str:
        """执行 fit_section_to_budget 相关逻辑。"""
        if token_budget <= 0:
            return ""

        header = f"## {section_title}\n"
        header_tokens = self._count_tokens(header, model)
        content_budget = max(0, token_budget - header_tokens)
        clipped = self._truncate_text_to_tokens(content.strip(), content_budget, model)

        if not clipped and content_budget > 0:
            clipped = self._truncate_text_to_tokens("(暂无内容)", content_budget, model)

        return f"{header}{clipped}".strip()

    async def compose_resident_system_text(
        self,
        *,
        user_id: str,
        employee_id: str,
        session: dict[str, Any],
        model: str,
        thresholds: WindowThresholds,
        read_memory_file: Callable[..., Any],
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> str:
        """组合并生成目标内容。"""
        tool_defs_text = self._render_tool_definitions_from_schema(tool_schemas or [])

        memory_entries: dict[str, str] = {}
        for file_name in (COMPRESSED_MEMORY_FILE, PERSONA_FILE, SCHEDULE_FILE, WORKBOOK_FILE):
            try:
                content = await read_memory_file(
                    user_id=user_id,
                    employee_id=employee_id,
                    file_name=file_name,
                )
            except Exception:  # noqa: BLE001
                content = ""
            normalized_content = self._normalize_memory_text(str(content))
            memory_entries[file_name] = normalized_content

        system_prompt_payload = compose_chat_system_prompt(
            window_preamble=self._system_preamble(thresholds),
            tool_definitions=tool_defs_text.strip(),
            memory_core=self._normalize_memory_text(memory_entries.get(COMPRESSED_MEMORY_FILE, "")),
            memory_persona=self._normalize_memory_text(memory_entries.get(PERSONA_FILE, "")),
            memory_schedule=self._normalize_memory_text(memory_entries.get(SCHEDULE_FILE, "")),
            memory_workbook=self._normalize_memory_text(memory_entries.get(WORKBOOK_FILE, "")),
        )

        summary_text = (session.get("workbench_summary") or "").strip() or "(当前暂无工作台摘要)"

        system_prompt_section = self.fit_section_to_budget(
            section_title=f"系统提示词与记忆文件（预算 {thresholds.system_prompt_limit} token）",
            content=system_prompt_payload,
            token_budget=thresholds.system_prompt_limit,
            model=model,
        )
        summary_section = self.fit_section_to_budget(
            section_title=f"工作台摘要（预算 {thresholds.summary_limit} token）",
            content=summary_text,
            token_budget=thresholds.summary_limit,
            model=model,
        )
        return f"{system_prompt_section}\n\n{summary_section}".strip()

    def row_token_count(self, row: dict[str, Any], model: str) -> int:
        """执行 row_token_count 相关逻辑。"""
        raw = row.get("token_count", 0)
        try:
            parsed = int(raw)
        except Exception:  # noqa: BLE001
            parsed = 0
        if parsed > 0:
            return parsed
        return self._count_tokens(str(row.get("content", "")), model)

    def take_latest_rows_by_token_budget(
        self,
        *,
        rows_ascending: list[dict[str, Any]],
        token_budget: int,
        model: str,
    ) -> list[dict[str, Any]]:
        """执行 take_latest_rows_by_token_budget 相关逻辑。"""
        if token_budget <= 0 or not rows_ascending:
            return []

        selected_reversed: list[dict[str, Any]] = []
        used_tokens = 0

        for row in reversed(rows_ascending):
            row_tokens = self.row_token_count(row, model)
            if used_tokens + row_tokens > token_budget:
                break
            selected_reversed.append(row)
            used_tokens += row_tokens

        return list(reversed(selected_reversed))

    def take_latest_rows_from_desc_by_budget(
        self,
        *,
        rows_descending: list[dict[str, Any]],
        token_budget: int,
        model: str,
    ) -> list[dict[str, Any]]:
        """执行 take_latest_rows_from_desc_by_budget 相关逻辑。"""
        if token_budget <= 0 or not rows_descending:
            return []

        selected_desc: list[dict[str, Any]] = []
        used_tokens = 0

        for row in rows_descending:
            row_tokens = self.row_token_count(row, model)
            if used_tokens + row_tokens > token_budget:
                break
            selected_desc.append(row)
            used_tokens += row_tokens

        selected_desc.reverse()
        return selected_desc

    def previous_role_from_resident_recent(self, rows: list[dict[str, Any]]) -> str | None:
        """执行 previous_role_from_resident_recent 相关逻辑。"""
        previous_role: str | None = None
        for row in reversed(rows):
            normalized_role = normalize_prompt_role(row.get("role", "assistant"))
            if normalized_role == "system":
                continue
            previous_role = "assistant" if normalized_role == "tool" else normalized_role
            break
        return previous_role
