"""Shared implementation of the ``validate`` stage (input data contracts + profiling)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from forge.context import StageContext
from forge.contracts import FrameContract, normalise_columns, validate_frame


def run_validation(ctx: StageContext, contracts: dict[str, FrameContract]) -> dict[str, Any]:
    """Validate every ingested parquet named in ``contracts`` (key = parquet stem)."""
    data_dir = ctx.dep("ingest") / "data"
    reports: list[dict[str, Any]] = []
    profile: dict[str, Any] = {}
    for stem, contract in contracts.items():
        path = data_dir / f"{stem}.parquet"
        if not path.exists():
            reports.append({"contract": contract.name, "ok": False, "errors": [f"parquet missing: {stem}"], "rows": 0})
            continue
        df = normalise_columns(pd.read_parquet(path))
        report = validate_frame(df, contract)
        report["parquet"] = path.name
        reports.append(report)
        desc = df.describe(include="all").astype(str).to_dict()
        profile[stem] = {"rows": int(len(df)), "columns": list(df.columns), "describe": desc,
                         "nulls": {c: int(df[c].isna().sum()) for c in df.columns}}
        ctx.log.info("validate.frame", contract=contract.name, ok=report["ok"], rows=report["rows"],
                     errors=report["errors"][:5])
    ok = all(r["ok"] for r in reports)
    ctx.write_json("validation_report.json", {"ok": ok, "frames": reports})
    ctx.write_json("data_profile.json", profile)
    if not ok:
        failed = [r["contract"] for r in reports if not r["ok"]]
        raise RuntimeError(f"input contracts violated: {failed}")
    return {"ok": ok, "frames": len(reports)}
