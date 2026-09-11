"""Data contracts for Problem D (time–frequency conflict detection and resolution)."""

from __future__ import annotations

import re

import pandas as pd

from forge.contracts import Column, FrameContract
from forge.xlsx import SheetContract, WorkbookContract

INTERVAL = re.compile(r"^\[(\d+),(\d+)\)$")


def _intervals_well_formed(df: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    for col, upper in (("频段区间", 100), ("时间区间", None)):
        for value in df[col].astype(str):
            match = INTERVAL.match(value.strip())
            if not match:
                errors.append(f"{col}: malformed interval {value!r}")
                continue
            lo, hi = int(match.group(1)), int(match.group(2))
            if not lo < hi:
                errors.append(f"{col}: empty interval {value!r}")
            if upper is not None and hi > upper:
                errors.append(f"{col}: {value!r} exceeds {upper} bands")
    return errors[:20]


INPUT_CONTRACTS: dict[str, FrameContract] = {
    "附件1__Sheet1": FrameContract(
        name="D.附件1.用频计划",
        columns=(
            Column("用频装备编号", "str", regex=r"[ABC]\d{3}", unique=True),
            Column("频段区间", "str", regex=r"\[\d+,\d+\)"),
            Column("时间区间", "str", regex=r"\[\d+,\d+\)"),
            Column("间隔时长", "int", min=1),
            Column("使用次数", "int", min=1),
        ),
        min_rows=150,
        max_rows=150,
        checks=(_intervals_well_formed,),
    ),
}

RESULT_CONTRACTS: list[WorkbookContract] = [
    WorkbookContract("result1.xlsx", "result1.xlsx", (
        SheetContract("Sheet1", min_rows=1, header_len=3, text_columns=(1, 2)),
    )),
    WorkbookContract("result2.xlsx", "result2.xlsx", (
        SheetContract("Sheet1", min_rows=1, header_len=4, text_columns=(0,)),
    )),
    WorkbookContract("result3.xlsx", "result3.xlsx", (
        SheetContract("Sheet1", min_rows=0, header_len=3),
    )),
    WorkbookContract("result4.xlsx", "result4.xlsx", (
        SheetContract("Sheet1", min_rows=1, header_len=5, text_columns=(0,)),
    )),
]
