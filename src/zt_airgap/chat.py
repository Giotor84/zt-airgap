"""Chat without a public API: browser -> localhost bridge -> S3 inbox -> Tier B listener -> S3 outbox.

The listener answers in two steps: (1) a deterministic tool computes the facts with pandas/Python,
(2) the LLM writes prose ONLY from those facts. With ``bedrock=None`` the facts are returned as text, which is
also the fallback when the model fails.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from .bedrock import converse_text
from .s3io import get_json, list_keys, move, put_json

Tool = Callable[[str, dict], dict]


def answer(message: str, filters: dict, tool: Tool, bedrock: Any = None, model_id: str = "") -> dict:
    facts = tool(message, filters)
    if bedrock is None:
        return {"answer": json.dumps(facts, ensure_ascii=False), "facts": facts, "status": "done", "llm": False}
    prompt = (
        "Answer the user's question in 2-5 sentences using ONLY these facts. Do not add numbers that are not in "
        f"the facts.\n\nQUESTION: {message}\n\nFACTS:\n{json.dumps(facts, ensure_ascii=False, indent=2)}"
    )
    try:
        text = converse_text(bedrock, model_id, prompt, max_tokens=600, temperature=0.15)
        return {"answer": text, "facts": facts, "status": "done", "llm": True}
    except Exception as exc:
        return {"answer": json.dumps(facts, ensure_ascii=False), "facts": facts, "status": "done", "llm": False,
                "warning": f"LLM unavailable: {type(exc).__name__}"}


def process_inbox(s3: Any, bucket: str, prefix: str, tool: Tool, bedrock: Any = None, model_id: str = "") -> int:
    """Handle every pending request once; returns how many were processed."""
    n = 0
    for key in list(list_keys(s3, bucket, f"{prefix}chat/inbox/")):
        req = get_json(s3, bucket, key)
        rid = req.get("request_id") or key.rsplit("/", 1)[-1].removesuffix(".json")
        try:
            out = answer(req.get("message", ""), req.get("filters", {}), tool, bedrock, model_id)
        except Exception as exc:
            out = {"answer": "", "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        out["request_id"] = rid
        put_json(s3, bucket, f"{prefix}chat/outbox/{rid}.json", out)
        move(s3, bucket, key, f"{prefix}chat/done/{rid}.json")
        n += 1
    return n


def run_listener(s3: Any, bucket: str, prefix: str, tool: Tool, bedrock: Any = None, model_id: str = "",
                 poll_seconds: float = 2.0, max_idle_minutes: Optional[float] = 60) -> None:
    """Poll the inbox until idle for ``max_idle_minutes`` (stops paying for an idle notebook)."""
    idle_since = time.monotonic()
    while True:
        if process_inbox(s3, bucket, prefix, tool, bedrock, model_id):
            idle_since = time.monotonic()
        elif max_idle_minutes is not None and time.monotonic() - idle_since > max_idle_minutes * 60:
            return
        time.sleep(poll_seconds)
