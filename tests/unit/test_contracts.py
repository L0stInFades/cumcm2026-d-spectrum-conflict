from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from forge.contracts import Column, FrameContract, validate_frame

CONTRACT = FrameContract(
    name="t",
    columns=(
        Column("t", "int", min=0, unique=True, monotonic="increasing", step=60),
        Column("v", "float", min=0, max=1),
    ),
    min_rows=2,
)


def test_valid_frame_passes() -> None:
    df = pd.DataFrame({"t": [0, 60, 120], "v": [0.1, 0.2, 0.3]})
    report = validate_frame(df, CONTRACT)
    assert report["ok"], report["errors"]


def test_violations_are_reported_precisely() -> None:
    df = pd.DataFrame({"t": [0, 60, 60], "v": [0.1, 1.5, np.nan], "extra": [1, 2, 3]})
    report = validate_frame(df, CONTRACT)
    joined = " | ".join(report["errors"])
    assert not report["ok"]
    assert "unexpected columns" in joined
    assert "duplicated" in joined
    assert "max 1.5 > 1" in joined
    assert "null" in joined
    assert "not increasing" in joined


def test_column_names_are_stripped() -> None:
    df = pd.DataFrame({"t ": [0, 60], " v": [0.5, 0.6]})
    assert validate_frame(df, CONTRACT)["ok"]


@given(st.lists(st.floats(min_value=0, max_value=1, allow_nan=False), min_size=2, max_size=40))
def test_property_ranges_within_bounds_always_pass(values: list[float]) -> None:
    df = pd.DataFrame({"t": np.arange(len(values)) * 60, "v": values})
    assert validate_frame(df, CONTRACT)["ok"]


def test_regex_and_custom_checks() -> None:
    contract = FrameContract(
        "ids", (Column("id", "str", regex=r"[ABC]\d{3}"),), checks=(lambda df: ["custom"] if len(df) > 1 else [],)
    )
    assert validate_frame(pd.DataFrame({"id": ["A001"]}), contract)["ok"]
    report = validate_frame(pd.DataFrame({"id": ["A001", "Z9"]}), contract)
    assert any("violate" in e for e in report["errors"]) and "custom" in report["errors"]
