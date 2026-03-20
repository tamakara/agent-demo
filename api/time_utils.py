"""API time helpers."""

from __future__ import annotations

from datetime import datetime, timezone


ISO_MILLIS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utc_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime(ISO_MILLIS_FORMAT)
