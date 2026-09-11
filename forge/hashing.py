"""Content hashing helpers (SHA-256 everywhere; JSON hashed in canonical form)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256_bytes(payload.encode("utf-8"))


def hash_tree(root: Path, ignore: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """Return ``{relative_posix_path: {"sha256": ..., "bytes": ...}}`` for every file under ``root``.

    Any path component contained in ``ignore`` excludes the file (directory names or file names).
    The result is sorted by path so that its canonical JSON digest is stable.
    """
    ignored = set(ignore)
    out: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if ignored & set(rel.parts):
            continue
        out[rel.as_posix()] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    return out


def tree_digest(tree: dict[str, dict[str, Any]]) -> str:
    return sha256_json({k: v["sha256"] for k, v in sorted(tree.items())})
