"""Prompt composition and message budgeting logic for app services."""

from __future__ import annotations

from typing import Any

from app.interfaces import IPromptTemplateRepository
from app.memory_specs import (
    ASSET_PLACEHOLDER_FILE,
    COMPRESSED_MEMORY_FILE,
    PERSONA_FILE,
    SCHEDULE_FILE,
    WORKBOOK_FILE,
)
from app.window_policy import WindowThresholds


class PromptComposer:
    def __init__(
        self,
        *,
        count_tokens,
        truncate_text_to_tokens,
        template_repository: IPromptTemplateRepository,
    ) -> None:
        self._count_tokens = count_tokens
        self._truncate_text_to_tokens = truncate_text_to_tokens
        self._template_repository = template_repository

    def render_tool_definitions_from_schema(self, tool_schemas: list[dict[str, Any]]) -> str:
        tool_names: list[str] = []
        seen: set[str] = set()
        for schema in tool_schemas:
            function_spec = schema.get("function", {})
            if not isinstance(function_spec, dict):
                continue

            tool_name = str(function_spec.get("name", "")).strip()
            if not tool_name or tool_name in seen:
                continue
            seen.add(tool_name)
            tool_names.append(tool_name)
        return self._template_repository.compose_tool_definitions(tool_names=tool_names)

    @staticmethod
    def _normalize_memory_text(raw_text: str) -> str:
        text = str(raw_text or "").strip()
        return text or "(暂无内容)"

    def clip_text_to_budget(
        self,
        *,
        content: str,
        token_budget: int,
        model: str,
    ) -> str:
        if token_budget <= 0:
            return ""

        normalized_budget = max(1, int(token_budget))
        clipped = self._truncate_text_to_tokens(content.strip(), normalized_budget, model)

        if not clipped:
            clipped = self._truncate_text_to_tokens("(暂无内容)", normalized_budget, model)

        return clipped.strip()

    async def compose_resident_system_text(
        self,
        *,
        user_id: str,
        employee_id: str,
        session: dict[str, Any],
        model: str,
        thresholds: WindowThresholds,
        read_memory_file,
        tool_schemas: list[dict[str, Any]] | None = None,
    ) -> str:
        tool_defs_text = self.render_tool_definitions_from_schema(tool_schemas or [])

        memory_entries: dict[str, str] = {}
        for file_name in (COMPRESSED_MEMORY_FILE, ASSET_PLACEHOLDER_FILE, PERSONA_FILE, SCHEDULE_FILE, WORKBOOK_FILE):
            try:
                content = await read_memory_file(
                    user_id=user_id,
                    employee_id=employee_id,
                    file_name=file_name,
                )
            except Exception:  # noqa: BLE001
                content = ""
            memory_entries[file_name] = self._normalize_memory_text(str(content))

        system_prompt_payload = self._template_repository.compose_chat_system_prompt(
            tool_definitions=tool_defs_text.strip(),
            memory_core=self._normalize_memory_text(memory_entries.get(COMPRESSED_MEMORY_FILE, "")),
            memory_file=self._normalize_memory_text(memory_entries.get(ASSET_PLACEHOLDER_FILE, "")),
            memory_persona=self._normalize_memory_text(memory_entries.get(PERSONA_FILE, "")),
            memory_schedule=self._normalize_memory_text(memory_entries.get(SCHEDULE_FILE, "")),
            memory_workbook=self._normalize_memory_text(memory_entries.get(WORKBOOK_FILE, "")),
            workbench_summary=self.clip_text_to_budget(
                content=(session.get("workbench_summary") or "").strip() or "(当前暂无工作台摘要)",
                token_budget=thresholds.summary_limit,
                model=model,
            ),
        )

        return self.clip_text_to_budget(
            content=system_prompt_payload,
            token_budget=thresholds.system_prompt_limit + thresholds.summary_limit,
            model=model,
        )

    def row_token_count(self, row: dict[str, Any], model: str) -> int:
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
