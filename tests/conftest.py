"""Shared test configuration: deterministic hypothesis profile, no on-disk example database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

settings.register_profile(
    "forge", database=None, deadline=None, max_examples=60, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile("forge")

REPO = Path(os.environ.get("FORGE_REPO", Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A minimal repository layout (configs only) for runtime tests that must not touch real data."""
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "default.toml").write_text("[run]\nseed = 7\n[paper]\nsources = []\n", encoding="utf-8")
    (tmp_path / "configs" / "project.json").write_text(
        '{"letter": "T", "package": "t", "problem_pdf": "T.pdf", "attachments_dir": "att", '
        '"templates_dir": "att/tpl", "result_files": []}',
        encoding="utf-8",
    )
    (tmp_path / "att" / "tpl").mkdir(parents=True)
    return tmp_path
