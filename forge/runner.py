"""Stage registry and executor. A stage is a function ``fn(ctx) -> metrics``.

Guarantees: one manifest per (run, stage); dependencies must be completed in the same run
(or copied from ``from_run``); a completed stage is skipped unless ``force``; failures are
recorded with a traceback and re-raised; the volume is committed after every stage.
"""

from __future__ import annotations

import importlib
import json
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import StageContext
from .hashing import hash_tree, tree_digest
from .manifest import Manifest

StageFn = Callable[[StageContext], dict[str, Any] | None]
CODE_IGNORE = (
    ".git",
    "artifacts",
    "releases",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".hypothesis",
    ".DS_Store",
    ".forge",
)


@dataclass(frozen=True)
class StageSpec:
    name: str
    fn: StageFn
    deps: tuple[str, ...]
    description: str


STAGES: dict[str, StageSpec] = {}


def stage(name: str, deps: Iterable[str] = (), description: str = "") -> Callable[[StageFn], StageFn]:
    def decorator(fn: StageFn) -> StageFn:
        if name in STAGES:
            raise ValueError(f"duplicate stage registration: {name}")
        doc = (fn.__doc__ or "").strip().splitlines()
        STAGES[name] = StageSpec(name, fn, tuple(deps), description or (doc[0] if doc else ""))
        return fn

    return decorator


def discover(repo: Path) -> None:
    project = json.loads((repo / "configs" / "project.json").read_text(encoding="utf-8"))
    importlib.import_module("pipelines.common.stages")
    importlib.import_module(f"pipelines.{project['package']}.stages")


def list_stages(repo: Path) -> list[dict[str, Any]]:
    discover(repo)
    return [{"name": s.name, "deps": list(s.deps), "description": s.description} for s in STAGES.values()]


def _raw_input_prefixes(repo: Path) -> tuple[str, ...]:
    project = json.loads((repo / "configs" / "project.json").read_text(encoding="utf-8"))
    return (project["problem_pdf"], project["attachments_dir"].rstrip("/") + "/")


def execute(
    stage_name: str,
    run_id: str,
    params: dict[str, Any],
    force: bool,
    repo: Path,
    vol: Path,
    commit: Callable[[], None] | None = None,
) -> dict[str, Any]:
    discover(repo)
    if stage_name == "all":
        results = [execute(s, run_id, params, force, repo, vol, commit) for s in params.get("stages", [])]
        return {
            "stage": "all",
            "run_id": run_id,
            "results": results,
            "status": "completed" if all(r.get("status") in {"completed", "skipped"} for r in results) else "failed",
        }
    if stage_name not in STAGES:
        raise KeyError(f"unknown stage {stage_name!r}; known stages: {sorted(STAGES)}")
    spec = STAGES[stage_name]
    run_dir = vol / "runs" / run_id
    stage_dir = run_dir / stage_name
    manifest_path = stage_dir / "manifest.json"

    if manifest_path.exists() and not force:
        previous = Manifest.read(manifest_path)
        if previous.status == "completed":
            return {
                "stage": stage_name,
                "run_id": run_id,
                "status": "skipped",
                "reason": "already completed in this run (use --force to rerun)",
                "outputs_digest": previous.outputs_digest,
            }

    deps_digest: dict[str, str] = {}
    for dep in spec.deps:
        dep_manifest = run_dir / dep / "manifest.json"
        if not dep_manifest.exists() and params.get("from_run"):
            source = vol / "runs" / str(params["from_run"]) / dep
            if (source / "manifest.json").exists():
                shutil.copytree(source, run_dir / dep, dirs_exist_ok=True)
        if not dep_manifest.exists():
            raise RuntimeError(
                f"stage '{stage_name}' requires '{dep}', which has not run in run {run_id} "
                f"(run it first, or pass from_run=<run_id> to reuse its outputs)"
            )
        dep_state = Manifest.read(dep_manifest)
        if dep_state.status != "completed":
            raise RuntimeError(f"dependency '{dep}' has status {dep_state.status!r} in run {run_id}")
        deps_digest[dep] = dep_state.outputs_digest

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    ctx = StageContext(run_id, stage_name, params, repo, vol)
    code_tree = hash_tree(repo, ignore=CODE_IGNORE)
    prefixes = _raw_input_prefixes(repo)
    inputs = {k: v for k, v in code_tree.items() if k.startswith(prefixes)}
    code_ref = {**dict(params.get("code_ref") or {}), "code_digest": tree_digest(code_tree), "files": len(code_tree)}
    manifest = Manifest.start(run_id, stage_name, params, code_ref, ctx.config.digest, deps_digest, inputs)
    manifest.write(manifest_path)
    ctx.log.info("stage.start", deps=list(spec.deps), description=spec.description, size=params.get("size"))
    t0 = time.monotonic()
    try:
        metrics = spec.fn(ctx) or {}
        ctx.flush_numbers()
        manifest.complete(stage_dir, metrics)
        ctx.log.info("stage.completed", duration_s=round(time.monotonic() - t0, 3), metrics=metrics)
    except BaseException as exc:
        manifest.fail(exc)
        ctx.log.error("stage.failed", error=repr(exc))
        manifest.write(manifest_path)
        ctx.log.close()
        if commit:
            commit()
        raise
    manifest.write(manifest_path)
    ctx.log.close()
    if commit:
        commit()
    return {
        "stage": stage_name,
        "run_id": run_id,
        "status": "completed",
        "duration_s": manifest.duration_s,
        "metrics": manifest.metrics,
        "outputs_digest": manifest.outputs_digest,
        "modal_task_id": manifest.runtime.get("modal_task_id"),
    }
