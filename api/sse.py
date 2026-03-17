"""SSE 事件帧构建工具。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from common.time_utils import utc_now_iso


@dataclass(slots=True)
class SSEEnvelopeBuilder:
    """SSE 事件包装器，负责维护事件序号与统一信封结构。"""
    request_id: str
    employee_id: str
    session_id: str
    seq: int = field(default=0)

    def frame(self, event_type: str, payload: dict[str, Any]) -> str:
        """构建单条 SSE 文本帧。"""
        self.seq += 1
        data = {
            "type": event_type,
            "seq": self.seq,
            "request_id": self.request_id,
            "ts": utc_now_iso(),
            "employee_id": self.employee_id,
            "session_id": self.session_id,
            "payload": payload,
        }
        body = json.dumps(data, ensure_ascii=False)
        return f"event: message\ndata: {body}\n\n"
