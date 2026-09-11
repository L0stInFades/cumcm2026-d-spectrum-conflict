"""Stage execution context: paths, config, params, logging, seeds and paper numbers."""

from __future__ import annotations

import json
import random
import re
import zlib
from pathlib import Path
from typing import Any

from .config import Config, load_config, load_project
from .events import EventLogger

_NUMBER_KEY = re.compile(r"^[A-Za-z]+$")


class StageContext:
    """Everything a stage needs. Stages must write only under ``stage_dir``."""

    def __init__(self, run_id: str, stage: str, params: dict[str, Any], repo: Path, vol: Path) -> None:
        self.run_id = run_id
        self.stage = stage
        self.params = dict(params)
        self.repo = repo
        self.vol = vol
        self.project = load_project(repo)
        overrides = self.params.get("config_overrides") or None
        self.config: Config = load_config(repo, self.params.get("profile"), overrides)
        self.run_dir = vol / "runs" / run_id
        self.stage_dir = self.run_dir / stage
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        self.log = EventLogger(self.stage_dir / "events.jsonl", run_id, stage)
        self._numbers: dict[str, str] = {}

    # ---- raw inputs (immutable, at repo root, exactly as delivered by the organisers) ----
    @property
    def problem_pdf(self) -> Path:
        return self.repo / self.project["problem_pdf"]

    @property
    def attachments(self) -> Path:
        return self.repo / self.project["attachments_dir"]

    @property
    def templates(self) -> Path:
        return self.repo / self.project["templates_dir"]

    # ---- outputs ----
    def out(self, *parts: str) -> Path:
        path = self.stage_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def dep(self, stage: str) -> Path:
        """Directory of a completed dependency stage in the same run (raises otherwise)."""
        directory = self.run_dir / stage
        manifest = directory / "manifest.json"
        if not manifest.exists():
            raise RuntimeError(f"dependency stage '{stage}' has not run in run {self.run_id}")
        status = json.loads(manifest.read_text(encoding="utf-8")).get("status")
        if status != "completed":
            raise RuntimeError(f"dependency stage '{stage}' has status {status!r} in run {self.run_id}")
        return directory

    def has_stage(self, stage: str) -> bool:
        manifest = self.run_dir / stage / "manifest.json"
        return manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")).get("status") == "completed"

    def dep_data(self, stage: str, name: str) -> Any:
        return json.loads((self.dep(stage) / name).read_text(encoding="utf-8"))

    # ---- parameters / configuration ----
    def param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def cfg(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    # ---- determinism ----
    def seed(self, salt: str = "") -> int:
        base = int(self.cfg("run.seed", 0))
        return (base + zlib.crc32(salt.encode("utf-8"))) % (2**31 - 1)

    def seed_everything(self, salt: str = "") -> int:
        value = self.seed(salt)
        random.seed(value)
        try:
            import numpy as np

            np.random.seed(value)
        except ImportError:  # pragma: no cover
            pass
        self.log.info("seed", salt=salt, value=value)
        return value

    # ---- numbers that flow into the paper as \val<Key> macros ----
    def number(self, key: str, value: Any, fmt: str | None = None) -> str:
        if not _NUMBER_KEY.match(key):
            raise ValueError(f"paper number keys must be letters only (TeX macro names); got {key!r}")
        if fmt is not None:
            text = format(value, fmt)
        elif isinstance(value, bool):
            text = str(value)
        elif isinstance(value, int):
            text = str(value)
        elif isinstance(value, float):
            text = f"{value:.4f}"
        else:
            text = str(value)
        self._numbers[key] = text
        return text

    def flush_numbers(self) -> None:
        if not self._numbers:
            return
        path = self.stage_dir / "numbers.json"
        merged: dict[str, str] = {}
        if path.exists():
            merged.update(json.loads(path.read_text(encoding="utf-8")))
        merged.update(self._numbers)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # ---- json helpers ----
    def write_json(self, name: str, obj: Any) -> Path:
        path = self.out(name)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))
