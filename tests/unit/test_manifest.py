from __future__ import annotations

from pathlib import Path

from forge.manifest import Manifest


def test_manifest_lifecycle_and_verification(tmp_path: Path) -> None:
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "out.json").write_text("{}")
    (stage_dir / "events.jsonl").write_text("{}\n")
    manifest = Manifest.start("run1", "stage", {"p": 1}, {"git_sha": "abc"}, "cfg", {"ingest": "d"}, {})
    assert manifest.status == "running" and manifest.runtime["python"]
    manifest.complete(stage_dir, {"m": 1.5})
    assert manifest.status == "completed"
    assert list(manifest.outputs) == ["out.json"]
    manifest.write(stage_dir / "manifest.json")
    loaded = Manifest.read(stage_dir / "manifest.json")
    assert loaded.outputs_digest == manifest.outputs_digest
    assert loaded.verify_outputs(stage_dir) == []
    (stage_dir / "out.json").write_text('{"x": 1}')
    assert loaded.verify_outputs(stage_dir) == ["sha256 mismatch: out.json"]


def test_manifest_failure_records_traceback() -> None:
    manifest = Manifest.start("run1", "stage", {}, {}, "cfg", {}, {})
    try:
        raise ValueError("boom")
    except ValueError as exc:
        manifest.fail(exc)
    assert manifest.status == "failed"
    assert manifest.error and manifest.error["type"] == "ValueError"
    assert manifest.duration_s is not None
