"""Deterministic packaging of support materials (stable member order and timestamps)."""

from __future__ import annotations

import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .hashing import sha256_file

FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SKIP_PARTS = {
    ".git",
    "__pycache__",
    ".DS_Store",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
    "artifacts",
    "releases",
    ".forge",
    "build",
}


def code_members(repo: Path, globs: Iterable[str]) -> list[tuple[str, Path]]:
    found: dict[str, Path] = {}
    for pattern in globs:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(repo)
            if SKIP_PARTS & set(rel.parts) or path.suffix == ".pyc":
                continue
            found[rel.as_posix()] = path
    return sorted(found.items())


def run_members(run_dir: Path, stages: Iterable[str], *, prefix: str = "runs") -> list[tuple[str, Path]]:
    members: list[tuple[str, Path]] = []
    for stage in stages:
        directory = run_dir / stage
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            rel = path.relative_to(directory)
            if path.is_file() and not (SKIP_PARTS & set(rel.parts)):
                members.append((f"{prefix}/{run_dir.name}/{stage}/{rel.as_posix()}", path))
    return members


def build_zip(members: Iterable[tuple[str, Path]], out: Path, *, comment: str = "") -> dict[str, Any]:
    ordered = sorted(dict(members).items())
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        if comment:
            zf.comment = comment.encode("utf-8")
        for name, source in ordered:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = source.read_bytes()
            total += len(data)
            zf.writestr(info, data)
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
        count = len(zf.namelist())
    if bad:
        raise RuntimeError(f"zip member failed CRC check: {bad}")
    return {
        "path": str(out),
        "members": count,
        "uncompressed_bytes": total,
        "bytes": out.stat().st_size,
        "sha256": sha256_file(out),
    }
