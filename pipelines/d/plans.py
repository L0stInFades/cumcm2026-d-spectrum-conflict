"""Plan data model for Problem D: parsing attachment rows, use intervals, cells and adjustments.

A plan occupies the band interval ``[f, f+w)`` during ``n`` uses; use ``k`` (0-based) occupies the
time interval ``[s + k(d+g), s + d + k(d+g))``. All intervals are half-open integers (MDR-0001).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

BANDS = 100
CATEGORIES = ("A", "B", "C")
INTERVAL = re.compile(r"^\s*\[\s*(\d+)\s*,\s*(\d+)\s*\)\s*$")


def parse_interval(text: Any) -> tuple[int, int]:
    """Parse ``[lo,hi)`` into ``(lo, hi)``; rejects malformed or empty intervals."""
    match = INTERVAL.match(str(text))
    if not match:
        raise ValueError(f"malformed half-open interval: {text!r}")
    lo, hi = int(match.group(1)), int(match.group(2))
    if lo >= hi:
        raise ValueError(f"empty interval: {text!r}")
    return lo, hi


def fmt_interval(lo: int, hi: int) -> str:
    """Format a half-open interval the way the attachments do: ``[lo,hi)``."""
    return f"[{lo},{hi})"


@dataclass(frozen=True)
class Plan:
    """One frequency-use plan (immutable)."""

    pid: str
    cat: str
    f: int  # first band occupied
    w: int  # number of bands occupied
    s: int  # start of the first use
    d: int  # duration of every use
    g: int  # gap between consecutive uses
    n: int  # number of uses

    @property
    def period(self) -> int:
        return self.d + self.g

    @property
    def f_end(self) -> int:
        return self.f + self.w

    @property
    def end(self) -> int:
        """Exclusive end time of the last use."""
        return self.s + self.d + (self.n - 1) * self.period

    def uses(self) -> list[tuple[int, int]]:
        """Half-open time intervals of the ``n`` uses, in chronological order."""
        return [(self.s + k * self.period, self.s + k * self.period + self.d) for k in range(self.n)]

    @property
    def n_cells(self) -> int:
        return self.w * self.d * self.n

    def freq_text(self) -> str:
        return fmt_interval(self.f, self.f_end)

    def time_text(self) -> str:
        return fmt_interval(self.s, self.s + self.d)

    def shifted(self, df: int = 0, dt: int = 0, gap: int | None = None) -> Plan:
        """Copy with the band start moved by ``df``, the time start by ``dt`` and/or a new gap."""
        return replace(self, f=self.f + df, s=self.s + dt, g=self.g if gap is None else gap)

    def record(self) -> dict[str, Any]:
        return asdict(self)


def plan_from_record(rec: dict[str, Any]) -> Plan:
    return Plan(
        str(rec["pid"]),
        str(rec["cat"]),
        int(rec["f"]),
        int(rec["w"]),
        int(rec["s"]),
        int(rec["d"]),
        int(rec["g"]),
        int(rec["n"]),
    )


def plan_from_row(pid: Any, freq: Any, time: Any, gap: Any, count: Any) -> Plan:
    """Build a plan from one attachment row (equipment id, band interval, time interval, gap, count)."""
    pid = str(pid).strip()
    f0, f1 = parse_interval(freq)
    t0, t1 = parse_interval(time)
    return Plan(pid, pid[0], f0, f1 - f0, t0, t1 - t0, int(gap), int(count))


def load_plans(parquet: Path) -> list[Plan]:
    """Read the ingested attachment sheet (parquet) into plans, in file order."""
    import pandas as pd

    df = pd.read_parquet(parquet)
    df.columns = [str(c).strip() for c in df.columns]
    return [
        plan_from_row(r["用频装备编号"], r["频段区间"], r["时间区间"], r["间隔时长"], r["使用次数"])
        for _, r in df.iterrows()
    ]


def horizon(plans: list[Plan]) -> int:
    """Latest exclusive end time over the plans (0 for an empty list)."""
    return max((p.end for p in plans), key=int, default=0)


def by_category(plans: list[Plan]) -> dict[str, list[Plan]]:
    out: dict[str, list[Plan]] = {c: [] for c in CATEGORIES}
    for p in plans:
        out.setdefault(p.cat, []).append(p)
    return out
