"""时间格式化与时间戳工具。"""

from __future__ import annotations

from datetime import datetime, timezone


ISO_MILLIS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now_iso() -> str:
    """返回 UTC ISO-8601 时间戳（毫秒）。"""
    now = datetime.now(timezone.utc)
    return now.strftime(ISO_MILLIS_FORMAT)
