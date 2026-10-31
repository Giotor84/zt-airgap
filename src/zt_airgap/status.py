"""Run status for a control dashboard: every pipeline writes ``status/{system}/latest.json`` after each run.

Read-only monitoring finds the real problems (a scraper silently stopped for months, a crash nobody saw).
Rules: pass the real time of the event (not "now") when back-filling, otherwise "silent" alarms are meaningless;
never put personal data in a status (counts and opaque ids only).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from .s3io import put_json

STATI = ("ok", "warning", "error", "running")


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)  # ':' in ISO timestamps breaks folder names on Windows


def write_status(s3: Any, bucket: str, prefix: str, system: str, state: str, *, counts: Optional[dict] = None,
                 message: str = "", event_time: Optional[str] = None, batch_id: Optional[str] = None) -> dict:
    if state not in STATI:
        raise ValueError(f"state must be one of {STATI}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = {"system": system, "state": state, "counts": counts or {}, "message": message,
           "event_time": event_time or now, "written_at": now, "batch_id": _safe(batch_id or now)}
    put_json(s3, bucket, f"{prefix}status/{_safe(system)}/latest.json", doc)
    put_json(s3, bucket, f"{prefix}status/{_safe(system)}/history/{doc['batch_id']}.json", doc)
    return doc


def is_silent(doc: dict, max_age_hours: float, now: Optional[datetime] = None) -> bool:
    """True when the last real event is older than expected for this system."""
    now = now or datetime.now(timezone.utc)
    t = datetime.fromisoformat(doc["event_time"])
    return (now - t).total_seconds() > max_age_hours * 3600
