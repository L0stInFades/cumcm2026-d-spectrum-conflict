"""Problem D: actions, cell model, lexicographic CP-SAT vs exhaustive enumeration, HiGHS agreement, validator."""

from __future__ import annotations

import pytest

from pipelines.d.plans import Plan
from pipelines.d.resolve import (
    Limits,
    Option,
    build_cell_model,
    canonical_levels,
    decisions_from_choice,
    enumerate_options,
    evaluate,
    level_upper_bounds,
    scheme_levels,
    separated_weights,
    solve_lexicographic_cpsat,
    solve_lexicographic_highs,
    solve_weighted_cpsat,
    strengthen,
    table_from_decisions,
)
from pipelines.d.synth import exhaustive_lexicographic, tiny_instance
from pipelines.d.validators import validate_resolution


def test_option_enumeration_respects_bounds_and_single_parameter() -> None:
    plan = Plan("C001", "C", 95, 3, 2, 2, 8, 12)
    opts = enumerate_options(plan, Limits(fmax=10, tmax=5))
    freq = sorted(o.delta for o in opts if o.kind == "freq")
    time = sorted(o.delta for o in opts if o.kind == "time")
    assert freq == [*range(-10, 0), 1, 2]  # band interval must stay inside [0,100)
    assert time == [-2, -1, 1, 2, 3, 4, 5]  # start must stay >= 0
    assert [o.kind for o in opts].count("keep") == 1 and [o.kind for o in opts].count("cancel") == 1
    assert all(o.kind != "gap" for o in opts)
    with_gap = enumerate_options(plan, Limits(fmax=10, tmax=5, gmax=10, gap_categories=("C",)))
    gaps = sorted(o.delta for o in with_gap if o.kind == "gap")
    assert gaps == [d for d in range(-7, 11) if d != 0]  # g' = 8 + delta >= 1
    assert Option("time", -3).amplitude == 6 and Option("freq", 4).amplitude == 4 and Option("gap", 5).amplitude == 5
    assert Option("freq", 2).apply(plan) == plan.shifted(df=2)
    assert Option("cancel").apply(plan) is None


def test_separated_weights_dominate_lower_levels() -> None:
    bounds = [20, 40, 90, 20, 40, 90, 1500]
    weights = separated_weights(bounds)
    for k in range(len(bounds) - 1):
        assert weights[k] > sum(w * b for w, b in zip(weights[k + 1 :], bounds[k + 1 :]))


@pytest.mark.parametrize("seed", [11, 12, 13, 14])
def test_cpsat_lexicographic_matches_exhaustive_and_validator(seed: int) -> None:
    plans = tiny_instance(seed, n_plans=5)
    limits = Limits(fmax=2, tmax=1)
    options = [enumerate_options(p, limits) for p in plans]
    model = build_cell_model(plans, options)
    levels = canonical_levels(model)
    truth = exhaustive_lexicographic(plans, limits, canonical_levels, model)
    res = solve_lexicographic_cpsat(model, levels, seed=1, workers=2, time_limit=60)
    assert res["all_optimal"] and res["vector"] == truth
    decisions = decisions_from_choice(model, res["chosen"])
    report = validate_resolution(
        plans, decisions, fmax=2, tmax=1, reported_table=table_from_decisions(decisions), reported_vector=res["vector"]
    )
    assert report["ok"], report["errors"]
    weighted = solve_weighted_cpsat(model, levels, seed=1, workers=2, time_limit=60)
    assert weighted["vector"] == truth
    highs = solve_lexicographic_highs(model, levels, seed=1, threads=2, time_limit=60)
    assert highs["all_optimal"] and highs["vector"] == truth
    assert evaluate(model, highs["chosen"], levels) == truth
    assert level_upper_bounds(model, levels)[-1] >= truth[-1]


def test_schemes_are_well_formed_and_forced_cancellation_is_detected() -> None:
    # two identical plans can never coexist: the optimum must cancel one of them (no shift can separate them
    # because they are also identical after any common shift? no - shifting one of them resolves it)
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    b = Plan("B001", "B", 0, 10, 0, 5, 60, 3)
    plans = [a, b]
    model = build_cell_model(plans, [enumerate_options(p, Limits(fmax=0, tmax=0)) for p in plans])
    for name in ("P", "T", "S", "W"):
        assert scheme_levels(name, model)
    res = solve_lexicographic_cpsat(model, canonical_levels(model), seed=0, workers=1, time_limit=30)
    assert res["vector"] == [0, 1, 0, 0, 0, 0, 0]  # the B plan is cancelled, never the A plan
    model2 = build_cell_model(plans, [enumerate_options(p, Limits(fmax=10, tmax=5)) for p in plans])
    res2 = solve_lexicographic_cpsat(model2, canonical_levels(model2), seed=0, workers=1, time_limit=30)
    assert res2["vector"][:6] == [0, 0, 0, 0, 1, 0]  # with shifts allowed: adjust the B plan instead


def test_validator_rejects_illegal_decisions() -> None:
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    b = Plan("C001", "C", 5, 3, 3, 2, 8, 12)
    bad = [
        {"pid": "A001", "kind": "keep", "delta": 0, "plan": a.record()},
        {"pid": "C001", "kind": "freq", "delta": 12, "plan": b.shifted(df=12).record()},
    ]
    report = validate_resolution([a, b], bad, fmax=10, tmax=5)
    assert not report["ok"] and any("exceeds" in e for e in report["errors"])
    two_params = [
        {"pid": "A001", "kind": "keep", "delta": 0, "plan": a.record()},
        {"pid": "C001", "kind": "time", "delta": 1, "plan": b.shifted(df=1, dt=1).record()},
    ]
    report = validate_resolution([a, b], two_params, fmax=10, tmax=5)
    assert not report["ok"] and any("changed fields" in e for e in report["errors"])
    unresolved = [
        {"pid": "A001", "kind": "keep", "delta": 0, "plan": a.record()},
        {"pid": "C001", "kind": "keep", "delta": 0, "plan": b.record()},
    ]
    report = validate_resolution([a, b], unresolved, fmax=10, tmax=5)
    assert not report["ok"] and report["remaining_conflicts"] == 1


def test_strengthen_detects_forced_cancellation_and_keeps_optimum() -> None:
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    b = Plan("B001", "B", 0, 10, 0, 5, 60, 3)
    model = build_cell_model([a, b], [enumerate_options(p, Limits(fmax=0, tmax=0)) for p in (a, b)])
    strength = strengthen(model)
    assert strength.forced == [(0, 1)] and strength.interacting_pairs == 1 and strength.groups
    for seed in (21, 22):
        plans = tiny_instance(seed, n_plans=5)
        limits = Limits(fmax=2, tmax=1)
        model = build_cell_model(plans, [enumerate_options(p, limits) for p in plans])
        truth = exhaustive_lexicographic(plans, limits, canonical_levels, model)
        res = solve_lexicographic_cpsat(
            model, canonical_levels(model), seed=1, workers=2, time_limit=60, strength=strengthen(model)
        )
        assert res["all_optimal"] and res["vector"] == truth
        highs = solve_lexicographic_highs(
            model,
            canonical_levels(model),
            seed=1,
            threads=2,
            time_limit=60,
            reference=truth,
            strength=strengthen(model),
        )
        assert highs["agrees_with_reference"] and highs["vector"] == truth
