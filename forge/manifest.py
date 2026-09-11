"""Run/stage manifests: the unit of lineage, reproducibility and audit."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import sys
import traceback
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hashing import hash_tree, tree_digest

TRACKED_PACKAGES = (
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "openpyxl",
    "matplotlib",
    "scikit-learn",
    "statsmodels",
    "ortools",
    "highspy",
    "numba",
    "cvxpy",
    "networkx",
    "pymupdf",
    "pytest",
    "hypothesis",
    "ruff",
    "mypy",
)
RECORD_FILES = ("manifest.json", "events.jsonl")  # run records, excluded from the outputs digest


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def runtime_info() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "modal_task_id": os.getenv("MODAL_TASK_ID"),
        "modal_is_remote": os.getenv("MODAL_IS_REMOTE") == "1" or os.getenv("MODAL_TASK_ID") is not None,
        "packages": packages,
        "env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "PYTHONHASHSEED")},
    }


@dataclass
class Manifest:
    schema: str = "forge.manifest/1"
    run_id: str = ""
    stage: str = ""
    status: str = "running"  # running | completed | failed
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    duration_s: float | None = None
    code_ref: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    config_digest: str = ""
    deps: dict[str, str] = field(default_factory=dict)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs_digest: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    @classmethod
    def start(
        cls,
        run_id: str,
        stage: str,
        params: dict[str, Any],
        code_ref: dict[str, Any],
        config_digest: str,
        deps: dict[str, str],
        inputs: dict[str, dict[str, Any]],
    ) -> Manifest:
        manifest = cls(
            run_id=run_id,
            stage=stage,
            params=params,
            code_ref=code_ref,
            config_digest=config_digest,
            deps=deps,
            inputs=inputs,
        )
        manifest.runtime = runtime_info()
        return manifest

    def complete(self, stage_dir: Path, metrics: dict[str, Any]) -> None:
        self.outputs = hash_tree(stage_dir, ignore=RECORD_FILES)
        self.outputs_digest = tree_digest(self.outputs)
        self.metrics = json.loads(json.dumps(metrics, default=str))
        self.status = "completed"
        self._finish()

    def fail(self, exc: BaseException) -> None:
        self.error = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        self.status = "failed"
        self._finish()

    def _finish(self) -> None:
        self.finished_at = utc_now()
        started = datetime.fromisoformat(self.started_at)
        self.duration_s = round((datetime.fromisoformat(self.finished_at) - started).total_seconds(), 3)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> Manifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def verify_outputs(self, stage_dir: Path) -> list[str]:
        """Return a list of mismatches between the manifest and the files on disk (empty == verified)."""
        problems: list[str] = []
        current = hash_tree(stage_dir, ignore=RECORD_FILES)
        for rel, meta in self.outputs.items():
            if rel not in current:
                problems.append(f"missing: {rel}")
            elif current[rel]["sha256"] != meta["sha256"]:
                problems.append(f"sha256 mismatch: {rel}")
        for rel in current:
            if rel not in self.outputs:
                problems.append(f"unexpected file: {rel}")
        return problems
