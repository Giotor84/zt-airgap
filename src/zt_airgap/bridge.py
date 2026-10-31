"""Tier C bridge: a localhost HTTP endpoint that relays chat requests to S3 and waits for the answer.

    python -m zt_airgap.bridge --bucket my-bucket --prefix myproject/ --port 8765

The bridge only moves JSON through S3 with the user's own credentials; it never calls the LLM. It listens on
127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .s3io import get_json, put_json


def relay(s3: Any, bucket: str, prefix: str, message: str, filters: dict | None = None,
          timeout_s: float = 180, poll_s: float = 1.0) -> dict:
    rid = str(uuid.uuid4())
    put_json(s3, bucket, f"{prefix}chat/inbox/{rid}.json", {
        "request_id": rid, "message": message, "filters": filters or {},
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return get_json(s3, bucket, f"{prefix}chat/outbox/{rid}.json")
        except Exception:
            time.sleep(poll_s)
    return {"request_id": rid, "status": "timeout", "answer": "No answer: is the Tier B listener running?"}


def serve(s3: Any, bucket: str, prefix: str, port: int = 8765) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "null")  # the dashboard is opened from file://
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, {})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/chat":
                return self._send(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length", 0))
            if length < 0 or length > 1_048_576:
                return self._send(413, {"error": "payload too large"})
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "invalid json"})
            if not isinstance(body, dict):
                return self._send(400, {"error": "json object expected"})
            self._send(200, relay(s3, bucket, prefix, str(body.get("message", "")), body.get("filters")))

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    import boto3
    serve(boto3.client("s3"), a.bucket, a.prefix, a.port)


if __name__ == "__main__":
    main()
