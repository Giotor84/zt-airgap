"""Release runtime modules to S3 as ONE unit, and load them on the air-gapped side.

No `pip install` on Tier B: the code travels through S3. A partial upload (one module newer than the others) is
the classic cause of ImportError or, worse, silent mismatches; so every release writes a manifest with SHA-256
of each file, and `bootstrap` refuses a set that does not match it.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .s3io import get_bytes, get_json, put_json
except ImportError:  # loaded flat from S3 in notebook cell 1, before the package exists
    from s3io import get_bytes, get_json, put_json


def release(s3: Any, bucket: str, prefix: str, files: Iterable[Path | str], version: str,
            root: Path | str | None = None) -> dict:
    """Upload all files under ``{prefix}modules/{version}/`` and write the manifest last.

    With ``root``, paths are kept relative to it (``root="src"`` ships the ``zt_airgap/`` package as a folder).
    """
    entries = {}
    for f in map(Path, files):
        data = f.read_bytes()
        name = f.relative_to(root).as_posix() if root else f.name
        key = f"{prefix}modules/{version}/{name}"
        s3.put_object(Bucket=bucket, Key=key, Body=data)
        entries[name] = hashlib.sha256(data).hexdigest()
    manifest = {"version": version, "files": entries,
                "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    put_json(s3, bucket, f"{prefix}modules/{version}/MANIFEST.json", manifest)
    put_json(s3, bucket, f"{prefix}modules/CURRENT.json", {"version": version})
    return manifest


class ReleaseMismatch(RuntimeError):
    pass


def bootstrap(s3: Any, bucket: str, prefix: str, target: Path | str | None = None,
              version: str | None = None) -> Path:
    """Download the current (or given) release, verify every hash, prepend the folder to sys.path."""
    version = version or get_json(s3, bucket, f"{prefix}modules/CURRENT.json")["version"]
    manifest = get_json(s3, bucket, f"{prefix}modules/{version}/MANIFEST.json")
    target = Path(target or tempfile.mkdtemp(prefix="airgap_modules_"))
    target.mkdir(parents=True, exist_ok=True)
    for name, digest in manifest["files"].items():
        p_rel = Path(name)
        if p_rel.is_absolute() or name.startswith(("/", "\\")) or p_rel.drive or ".." in p_rel.parts:
            raise ReleaseMismatch(f"unsafe path in MANIFEST: {name}")
        data = get_bytes(s3, bucket, f"{prefix}modules/{version}/{name}")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ReleaseMismatch(f"{name} does not match MANIFEST of release {version}")
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(data)
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    return target
