"""Minimal S3 helpers used by every tier, plus an in-memory fake with the same API for tests.

Only the boto3 calls the template needs: put_object, get_object, list_objects_v2, delete_object.
"""
from __future__ import annotations

import io
import threading
import json
from typing import Any, Iterator


def put_json(s3: Any, bucket: str, key: str, obj: Any) -> None:
    body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def get_json(s3: Any, bucket: str, key: str) -> Any:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8"))


def get_bytes(s3: Any, bucket: str, key: str) -> bytes:
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def list_keys(s3: Any, bucket: str, prefix: str) -> Iterator[str]:
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        for obj in page.get("Contents", []):
            yield obj["Key"]
        if not page.get("IsTruncated"):
            return
        token = page["NextContinuationToken"]


def move(s3: Any, bucket: str, src: str, dst: str) -> None:
    s3.put_object(Bucket=bucket, Key=dst, Body=get_bytes(s3, bucket, src))
    s3.delete_object(Bucket=bucket, Key=src)


class FakeS3:
    """In-memory stand-in for a boto3 S3 client (tests and local dry runs)."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self._lock = threading.RLock()

    def put_object(self, Bucket: str, Key: str, Body: bytes | str, **_: Any) -> dict:
        with self._lock:
            self.objects[(Bucket, Key)] = Body.encode("utf-8") if isinstance(Body, str) else bytes(Body)
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:
        with self._lock:
            try:
                return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}
            except KeyError:
                raise KeyError(f"NoSuchKey: s3://{Bucket}/{Key}") from None

    def list_objects_v2(self, Bucket: str, Prefix: str = "", **_: Any) -> dict:
        with self._lock:
            keys = sorted(k for b, k in list(self.objects) if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}

    def delete_object(self, Bucket: str, Key: str) -> dict:
        with self._lock:
            self.objects.pop((Bucket, Key), None)
        return {}
