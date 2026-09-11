"""Problem D: plan semantics, the two detectors and the independent cell-set validator."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from pipelines.d.detect import detect_bandsweep, detect_pairwise, overlapping_uses, plans_conflict
from pipelines.d.plans import Plan, fmt_interval, parse_interval, plan_from_row
from pipelines.d.synth import synthetic_instance
from pipelines.d.validators import cell_set, conflicts_by_cells, validate_detection


def test_problem_statement_example_a001() -> None:
    plan = plan_from_row("A001", "[80,90)", "[35,40)", 60, 3)
    assert plan.cat == "A" and plan.w == 10 and plan.d == 5 and plan.period == 65
    assert plan.uses() == [(35, 40), (100, 105), (165, 170)]
    assert plan.end == 170 and plan.n_cells == 150
    assert parse_interval(" [3, 7) ") == (3, 7) and fmt_interval(3, 7) == "[3,7)"


def test_half_open_intervals_do_not_touch() -> None:
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    b = Plan("B001", "B", 10, 15, 0, 3, 40, 4)  # bands [10,25) touch [0,10) without overlap
    c = Plan("C001", "C", 5, 3, 5, 2, 8, 1)  # single use [5,7) touches [0,5)
    d = Plan("C002", "C", 5, 3, 4, 2, 8, 1)  # single use [4,6) overlaps [0,5)
    e = Plan("C003", "C", 5, 3, 5, 2, 8, 12)  # 7th use [65,67) overlaps A's second use [65,70)
    assert not plans_conflict(a, b) and not plans_conflict(a, c) and plans_conflict(a, d)
    assert overlapping_uses(a, d) == [(0, 0)] and overlapping_uses(a, e) == [(1, 6)]


def test_detectors_agree_with_cell_sets_on_synthetic_instances() -> None:
    for seed in (1, 2, 3):
        plans = synthetic_instance(60, seed)
        pairs = detect_pairwise(plans)
        assert pairs == detect_bandsweep(plans)
        truth = conflicts_by_cells(plans)
        assert [(plans[i].pid, plans[j].pid) for i, j in pairs] == truth
        report = validate_detection(plans, truth)
        assert report["ok"] and report["truth_pairs"] == len(pairs)


def test_validate_detection_flags_missing_and_extra() -> None:
    plans = synthetic_instance(40, 7)
    truth = conflicts_by_cells(plans)
    assert truth, "instance must contain conflicts"
    report = validate_detection(plans, truth[1:] + [("A001", "A002")])
    assert not report["ok"] and report["missing"] == truth[:1]
    assert ("A001", "A002") in report["extra"] or truth[0] == ("A001", "A002")


plan_strategy = st.builds(
    Plan,
    pid=st.just("X"),
    cat=st.just("C"),
    f=st.integers(0, 12),
    w=st.integers(1, 4),
    s=st.integers(0, 15),
    d=st.integers(1, 3),
    g=st.integers(1, 6),
    n=st.integers(1, 4),
)


@given(plan_strategy, plan_strategy)
def test_property_interval_arithmetic_matches_cell_sets(a: Plan, b: Plan) -> None:
    assert plans_conflict(a, b) == bool(cell_set(a) & cell_set(b))
    assert len(cell_set(a)) == a.n_cells
