"""TOML configuration with profile overlays and dotted access."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .hashing import sha256_json

_MISSING = object()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Read-only dotted-access view over a merged configuration mapping."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = json.loads(json.dumps(data))

    def get(self, key: str, default: Any = None) -> Any:
        cursor: Any = self._data
        for part in key.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return default
            cursor = cursor[part]
        return cursor

    def __getitem__(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def section(self, key: str) -> dict[str, Any]:
        value = self.get(key, {})
        return dict(value) if isinstance(value, dict) else {}

    def as_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._data))

    @property
    def digest(self) -> str:
        return sha256_json(self._data)


def load_project(repo: Path) -> dict[str, Any]:
    return json.loads((repo / "configs" / "project.json").read_text(encoding="utf-8"))


def load_config(repo: Path, profile: str | None = None, overrides: dict[str, Any] | None = None) -> Config:
    data = tomllib.loads((repo / "configs" / "default.toml").read_text(encoding="utf-8"))
    if profile:
        data = deep_merge(data, tomllib.loads((repo / "configs" / f"{profile}.toml").read_text(encoding="utf-8")))
    if overrides:
        data = deep_merge(data, overrides)
    return Config(data)
