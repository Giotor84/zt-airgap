"""Amazon Bedrock `converse` behind a corporate proxy, with robust JSON parsing and a fake client for tests.

On an air-gapped SageMaker instance there is no public internet, but AWS endpoints (S3, Bedrock Runtime) are
reachable through the corporate proxy. Credentials come from the instance IAM role, never from code.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def make_client(region: Optional[str] = None, proxy: Optional[str] = None, read_timeout: int = 120) -> Any:
    """boto3 bedrock-runtime client. Proxy from argument or AIRGAP_PROXY / HTTPS_PROXY ("host:port")."""
    import boto3
    from botocore.config import Config

    proxy = proxy or os.environ.get("AIRGAP_PROXY") or os.environ.get("HTTPS_PROXY")
    cfg = Config(
        proxies={"http": proxy, "https": proxy} if proxy else None,
        connect_timeout=5, read_timeout=read_timeout, retries={"max_attempts": 3, "mode": "standard"},
    )
    return boto3.client("bedrock-runtime", config=cfg, region_name=region or os.environ.get("AWS_REGION", "eu-central-1"))


class EmptyResponse(RuntimeError):
    """The model returned no text (keep stopReason and usage to understand why)."""

    def __init__(self, stop_reason: str, usage: dict):
        super().__init__(f"empty response, stopReason={stop_reason}, usage={usage}")
        self.stop_reason, self.usage = stop_reason, usage


def converse_text(client: Any, model_id: str, prompt: str, *, max_tokens: int = 2000,
                  temperature: float = 0.2, system: Optional[str] = None) -> str:
    kw: dict[str, Any] = {
        "modelId": model_id,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature, "topP": 0.9},
    }
    if system:
        kw["system"] = [{"text": system}]
    resp = client.converse(**kw)
    parts = resp.get("output", {}).get("message", {}).get("content", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise EmptyResponse(resp.get("stopReason", "?"), resp.get("usage", {}))
    return text


def parse_json(text: str) -> Any:
    """JSON from a model answer: ```json fences, or the first valid {...} / [...] value."""
    m = _FENCE.search(text)
    candidate = (m.group(1) if m else text).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(candidate):
            if ch in "{[":
                try:
                    val, _ = decoder.raw_decode(candidate, idx)
                    return val
                except json.JSONDecodeError:
                    continue
        raise


def converse_json(client: Any, model_id: str, prompt: str, *, attempts: int = 2, **kw: Any) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        text = converse_text(client, model_id, prompt if i == 0 else prompt + "\n\nAnswer with valid JSON only.", **kw)
        try:
            return parse_json(text)
        except json.JSONDecodeError as exc:
            last = exc
    raise ValueError(f"no valid JSON after {attempts} attempts") from last


class FakeBedrock:
    """Returns canned answers: ``FakeBedrock(lambda prompt: '{"ok": true}')``. Records every call."""

    def __init__(self, answer: Callable[[str], str]):
        self.answer, self.calls = answer, []

    def converse(self, **kw: Any) -> dict:
        prompt = kw["messages"][0]["content"][0]["text"]
        self.calls.append(kw)
        return {"output": {"message": {"content": [{"text": self.answer(prompt)}]}}, "stopReason": "end_turn",
                "usage": {"inputTokens": len(prompt) // 4, "outputTokens": 10}}
