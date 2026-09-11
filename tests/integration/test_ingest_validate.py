"""End-to-end ingest + validate against the real attachments (runs inside Modal where /repo exists)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge import runner

REPO = Path(os.environ.get("FORGE_REPO", "/repo"))
pytestmark = pytest.mark.integration


@pytest.mark.skipif(not (REPO / "configs" / "project.json").exists(), reason="repository inputs not mounted")
def test_ingest_then_validate_on_real_inputs(tmp_path: Path) -> None:
    vol = tmp_path / "vol"
    ingest = runner.execute("ingest", "itest", {"code_ref": {"git_sha": "test"}}, False, REPO, vol)
    assert ingest["status"] == "completed" and ingest["metrics"]["files"] >= 1
    inventory = json.loads((vol / "runs" / "itest" / "ingest" / "inventory.json").read_text(encoding="utf-8"))
    assert any(not f["template"] for f in inventory["files"])
    validate = runner.execute("validate", "itest", {}, False, REPO, vol)
    assert validate["status"] == "completed" and validate["metrics"]["ok"]
