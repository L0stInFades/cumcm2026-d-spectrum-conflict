"""Problem D: report helpers (tables) on hand-made inputs."""

from __future__ import annotations

from pipelines.d.plans import Plan
from pipelines.d.report import _cancelled_rows, _table1, _vector_text
from pipelines.d.resolve import Limits


def test_cancelled_rows_explain_each_cancelled_plan() -> None:
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    c1 = Plan("C001", "C", 5, 3, 3, 2, 8, 12)
    c2 = Plan("C002", "C", 95, 3, 3, 2, 8, 12)
    decisions = [
        {"pid": "A001", "kind": "keep", "delta": 0, "plan": a.record()},
        {"pid": "C001", "kind": "cancel", "delta": 0, "plan": None},
        {"pid": "C002", "kind": "cancel", "delta": 0, "plan": None},
    ]
    conflicts = [{"id1": "A001", "id2": "C001"}]
    rows = _cancelled_rows([a, c1, c2], decisions, conflicts, Limits(fmax=10, tmax=5))
    assert [r[0] for r in rows] == ["C001", "C002"]
    assert rows[0][3] == 1 and rows[0][4] == 1  # one neighbour, which is an A plan
    assert rows[1][3] == 0 and rows[1][4] == 0
    assert rows[0][5] == 15 + 8  # band start 5: shifts -5..10 minus 0 (15); time start 3: shifts -3..5 minus 0 (8)
    assert rows[1][5] == 12 + 8  # band start 95: only -10..2 (12 shifts) keep the plan inside [0,100)


def test_table1_and_vector_text() -> None:
    table = {
        "A": {"keep": 1, "adjust": 2, "cancel": 0},
        "B": {"keep": 0, "adjust": 0, "cancel": 1},
        "C": {"keep": 3, "adjust": 4, "cancel": 5},
    }
    rows = _table1(table)
    assert rows[-1] == ["合计", 4, 6, 6]
    assert _vector_text([0, 1, 2]) == "(0, 1, 2)" and _vector_text(None) == "-"
