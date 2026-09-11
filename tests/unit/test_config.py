from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import Config, deep_merge, load_config


def test_deep_merge_is_recursive_and_non_destructive() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    merged = deep_merge(base, {"a": {"y": 3}, "c": 4})
    assert merged == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}
    assert base == {"a": {"x": 1, "y": 2}, "b": 1}


def test_config_dotted_access_and_digest() -> None:
    cfg = Config({"paper": {"sources": ["q1"], "max_body_pages": 30}})
    assert cfg.get("paper.max_body_pages") == 30
    assert cfg.get("paper.missing", "d") == "d"
    assert cfg["paper.sources"] == ["q1"]
    with pytest.raises(KeyError):
        cfg["nope.nope"]
    assert cfg.digest == Config({"paper": {"max_body_pages": 30, "sources": ["q1"]}}).digest


def test_load_config_with_profile_and_overrides(tmp_repo: Path) -> None:
    (tmp_repo / "configs" / "fast.toml").write_text("[run]\nseed = 99\n", encoding="utf-8")
    cfg = load_config(tmp_repo, profile="fast", overrides={"paper": {"sources": ["x"]}})
    assert cfg.get("run.seed") == 99
    assert cfg.get("paper.sources") == ["x"]
