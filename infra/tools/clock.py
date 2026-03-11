"""系统时钟工具实现。"""

from __future__ import annotations

import json
from datetime import datetime, timezone as dt_timezone
from typing import Any

from app.ports.repositories import ClockPort


class SystemClock(ClockPort):
    """系统时间工具实现。"""

    async def get_current_time(self) -> str:
        """返回当前 UTC 与本地时间信息。"""
        now_utc = datetime.now(dt_timezone.utc)
        now_local = now_utc.astimezone()
        payload: dict[str, Any] = {
            "utc_time": now_utc.isoformat(),
            "local_time": now_local.isoformat(),
            "local_timezone": str(now_local.tzinfo),
            "unix_timestamp": int(now_utc.timestamp()),
        }
        return json.dumps(payload, ensure_ascii=False)

