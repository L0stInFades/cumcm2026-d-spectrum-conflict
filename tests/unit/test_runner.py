from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge import runner
from forge.context import StageContext


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "STAGES", {})
    monkeypatch.setattr(runner, "discover", lambda repo: None)


def test_execute_records_manifest_skips_reruns_and_enforces_deps(tmp_repo: Path, tmp_path: Path) -> None:
    vol = tmp_path / "vol"

    @runner.stage("first", description="first stage")
    def first(ctx: StageContext) -> dict:
        ctx.out("a.txt").write_text("hello")
        ctx.number("Answer", 42)
        return {"n": 1}

    @runner.stage("second", deps=("first",))
    def second(ctx: StageContext) -> dict:
        assert (ctx.dep("first") / "a.txt").read_text() == "hello"
        return {"ok": True}

    with pytest.raises(RuntimeError):
        runner.execute("second", "r1", {}, False, tmp_repo, vol)
    result = runner.execute("first", "r1", {"code_ref": {"git_sha": "x"}}, False, tmp_repo, vol)
    assert result["status"] == "completed" and result["metrics"] == {"n": 1}
    manifest = json.loads((vol / "runs" / "r1" / "first" / "manifest.json").read_text())
    assert manifest["status"] == "completed" and "a.txt" in manifest["outputs"] and "numbers.json" in manifest["outputs"]
    assert json.loads((vol / "runs" / "r1" / "first" / "numbers.json").read_text()) == {"Answer": "42"}
    assert runner.execute("first", "r1", {}, False, tmp_repo, vol)["status"] == "skipped"
    assert runner.execute("second", "r1", {}, False, tmp_repo, vol)["status"] == "completed"
    combined = runner.execute("all", "r1", {"stages": ["first", "second"]}, False, tmp_repo, vol)
    assert combined["status"] == "completed" and [r["status"] for r in combined["results"]] == ["skipped", "skipped"]


def test_failed_stage_writes_failed_manifest(tmp_repo: Path, tmp_path: Path) -> None:
    vol = tmp_path / "vol"

    @runner.stage("bad")
    def bad(ctx: StageContext) -> dict:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        runner.execute("bad", "r1", {}, False, tmp_repo, vol)
    manifest = json.loads((vol / "runs" / "r1" / "bad" / "manifest.json").read_text())
    assert manifest["status"] == "failed" and manifest["error"]["message"] == "boom"


def test_from_run_copies_dependency_outputs(tmp_repo: Path, tmp_path: Path) -> None:
    vol = tmp_path / "vol"

    @runner.stage("base")
    def base(ctx: StageContext) -> dict:
        ctx.out("x.txt").write_text("x")
        return {}

    @runner.stage("child", deps=("base",))
    def child(ctx: StageContext) -> dict:
        return {"seen": (ctx.dep("base") / "x.txt").read_text()}

    runner.execute("base", "old", {}, False, tmp_repo, vol)
    result = runner.execute("child", "new", {"from_run": "old"}, False, tmp_repo, vol)
    assert result["metrics"] == {"seen": "x"}
