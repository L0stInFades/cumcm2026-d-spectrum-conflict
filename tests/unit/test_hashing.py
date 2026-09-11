from __future__ import annotations

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from forge.hashing import hash_tree, sha256_bytes, sha256_json, tree_digest


@given(st.binary())
def test_sha256_bytes_is_deterministic(data: bytes) -> None:
    assert sha256_bytes(data) == sha256_bytes(data)
    assert len(sha256_bytes(data)) == 64


@given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers() | st.floats(allow_nan=False) | st.text(max_size=5), max_size=6))
def test_sha256_json_ignores_key_order(mapping: dict) -> None:
    reversed_mapping = dict(reversed(list(mapping.items())))
    assert sha256_json(mapping) == sha256_json(reversed_mapping)


def test_hash_tree_ignores_records_and_is_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    tree = hash_tree(tmp_path, ignore=("manifest.json", "__pycache__"))
    assert list(tree) == ["a.txt", "b.txt"]
    digest = tree_digest(tree)
    (tmp_path / "manifest.json").write_text('{"changed": true}')
    assert tree_digest(hash_tree(tmp_path, ignore=("manifest.json", "__pycache__"))) == digest
