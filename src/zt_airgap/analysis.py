"""Tier B per-entity analysis: numbers are computed in Python, the LLM only interprets them.

Golden rule: if a value can be computed (ratio, count, filter, date), it is computed here and passed to the
model as evidence. After the call, every numeric field the model echoes is overwritten with the computed value,
so a hallucinated number never reaches the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .bedrock import converse_json
from .s3io import get_json, list_keys, put_json

DEFAULT_SCHEMA = {
    "summary": "string, 2-4 sentences",
    "risks": ["string"],
    "recommendations": ["string"],
    "qualitative_score": "one of: low | medium | high",
}


def build_prompt(record: dict, schema: dict = DEFAULT_SCHEMA, instructions: str = "") -> str:
    evidence = {k: record.get(k) for k in ("attributes", "metrics_precalc", "history") if k in record}
    return (
        "You analyse one record. Use ONLY the evidence below. Do not compute new numbers: the metrics are already "
        "computed and correct. If the evidence is not enough, say so.\n"
        f"{instructions}\n\nEVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n\n"
        f"Answer with one JSON object with this shape:\n{json.dumps(schema, indent=2)}"
    )


def post_process(analysis: dict, record: dict) -> dict:
    """Overwrite with the computed values any metric the model repeated (or changed)."""
    out = dict(analysis)
    out["metrics"] = dict(record.get("metrics_precalc", {}))
    return out


def load_records(s3: Any, bucket: str, prefix: str) -> dict[str, dict]:
    recs = {}
    for key in list_keys(s3, bucket, f"{prefix}records/"):
        if key.endswith("/record.json"):
            rec = get_json(s3, bucket, key)
            recs[str(rec["entity_id"])] = rec
    return recs


def analyse_all(s3: Any, bucket: str, prefix: str, bedrock: Any, model_id: str,
                records: Optional[dict[str, dict]] = None,
                prompt_fn: Callable[[dict], str] = build_prompt) -> dict[str, dict]:
    """Analyse every record, persist ``ai_analysis/{id}/analysis_{ts}.json``; failures are recorded, not hidden."""
    records = records if records is not None else load_records(s3, bucket, prefix)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = {}
    for eid, rec in records.items():
        try:
            ai = post_process(converse_json(bedrock, model_id, prompt_fn(rec), max_tokens=1500, temperature=0.2), rec)
            ai["status"] = "ok"
        except Exception as exc:  # one failing record must not stop the batch
            ai = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        ai.update({"entity_id": eid, "model_id": model_id, "generated_at": ts})
        put_json(s3, bucket, f"{prefix}ai_analysis/{eid}/analysis_{ts}.json", ai)
        results[eid] = ai
    return results
