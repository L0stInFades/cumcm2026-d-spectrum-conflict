"""Lightweight DataFrame contracts (schema + range + monotonicity + custom checks)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Column:
    name: str
    kind: str = "any"  # int | float | number | str | datetime | any
    nullable: bool = False
    min: float | None = None
    max: float | None = None
    regex: str | None = None
    unique: bool = False
    monotonic: str | None = None  # increasing | non_decreasing | decreasing | non_increasing
    allowed: tuple[Any, ...] | None = None
    step: float | None = None  # constant difference between consecutive values


@dataclass(frozen=True)
class FrameContract:
    name: str
    columns: tuple[Column, ...]
    min_rows: int = 1
    max_rows: int | None = None
    extra_columns: str = "forbid"  # forbid | allow
    checks: tuple[Callable[[pd.DataFrame], list[str]], ...] = ()


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = pd.Index([str(c).strip() for c in out.columns])
    return out


def validate_frame(df: pd.DataFrame, contract: FrameContract) -> dict[str, Any]:
    df = normalise_columns(df)
    errors: list[str] = []
    warnings: list[str] = []
    expected = [c.name for c in contract.columns]
    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]
    if missing:
        errors.append(f"missing columns: {missing}")
    if extra and contract.extra_columns == "forbid":
        errors.append(f"unexpected columns: {extra}")
    n = len(df)
    if n < contract.min_rows:
        errors.append(f"rows {n} < min_rows {contract.min_rows}")
    if contract.max_rows is not None and n > contract.max_rows:
        errors.append(f"rows {n} > max_rows {contract.max_rows}")

    for col in contract.columns:
        if col.name not in df.columns:
            continue
        series = df[col.name]
        nulls = int(series.isna().sum())
        if nulls and not col.nullable:
            errors.append(f"{col.name}: {nulls} null values")
        values = series.dropna()
        if col.kind in {"int", "float", "number"}:
            numeric = pd.to_numeric(values, errors="coerce")
            bad = int(numeric.isna().sum())
            if bad:
                errors.append(f"{col.name}: {bad} non-numeric values")
            numeric = numeric.dropna().astype(float)
            if col.kind == "int" and len(numeric) and not np.all(np.mod(numeric.to_numpy(), 1) == 0):
                errors.append(f"{col.name}: non-integer values present")
            if col.min is not None and len(numeric) and float(numeric.min()) < col.min:
                errors.append(f"{col.name}: min {numeric.min()} < {col.min}")
            if col.max is not None and len(numeric) and float(numeric.max()) > col.max:
                errors.append(f"{col.name}: max {numeric.max()} > {col.max}")
            if col.monotonic and len(numeric) > 1:
                diff = np.diff(numeric.to_numpy())
                ok = {
                    "increasing": bool((diff > 0).all()),
                    "non_decreasing": bool((diff >= 0).all()),
                    "decreasing": bool((diff < 0).all()),
                    "non_increasing": bool((diff <= 0).all()),
                }[col.monotonic]
                if not ok:
                    errors.append(f"{col.name}: not {col.monotonic}")
            if col.step is not None and len(numeric) > 1:
                diff = np.diff(numeric.to_numpy())
                if not np.allclose(diff, col.step):
                    errors.append(f"{col.name}: step is not constant {col.step} (min {diff.min()}, max {diff.max()})")
        elif col.kind == "str":
            if col.regex:
                pattern = re.compile(col.regex)
                bad_values = [str(v) for v in values.astype(str) if not pattern.fullmatch(str(v))]
                if bad_values:
                    errors.append(f"{col.name}: {len(bad_values)} values violate /{col.regex}/, e.g. {bad_values[:3]}")
        elif col.kind == "datetime":
            parsed = pd.to_datetime(values, errors="coerce")
            bad = int(parsed.isna().sum())
            if bad:
                errors.append(f"{col.name}: {bad} unparsable datetimes")
        if col.unique and values.duplicated().any():
            errors.append(f"{col.name}: {int(values.duplicated().sum())} duplicated values")
        if col.allowed is not None:
            unexpected = sorted(set(values.unique()) - set(col.allowed), key=str)
            if unexpected:
                errors.append(f"{col.name}: values outside allowed set: {unexpected[:5]}")

    for check in contract.checks:
        try:
            errors.extend(check(df))
        except Exception as exc:
            errors.append(f"check {getattr(check, '__name__', check)!r} raised {exc!r}")

    return {
        "contract": contract.name,
        "ok": not errors,
        "rows": n,
        "columns": list(df.columns),
        "errors": errors,
        "warnings": warnings,
    }
