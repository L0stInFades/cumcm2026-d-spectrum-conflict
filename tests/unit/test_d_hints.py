"""Problem D: warm-start hints mapped from recorded decisions, and the HiGHS per-level cross-check."""

from __future__ import annotations

from pipelines.d.plans import Plan
from pipelines.d.resolve import (
    Limits,
    build_cell_model,
    canonical_levels,
    decisions_from_choice,
    enumerate_options,
    evaluate,
    hint_from_decisions,
    hint_is_feasible,
    solve_lexicographic_cpsat,
    solve_lexicographic_highs,
)
from pipelines.d.synth import tiny_instance


def _model(plans: list[Plan], limits: Limits):  # type: ignore[no-untyped-def]
    return build_cell_model(plans, [enumerate_options(p, limits) for p in plans])


def test_hint_round_trips_and_falls_back_to_keep() -> None:
    plans = tiny_instance(31, n_plans=5)
    model = _model(plans, Limits(fmax=2, tmax=1))
    res = solve_lexicographic_cpsat(model, canonical_levels(model), seed=1, workers=2, time_limit=60)
    decisions = decisions_from_choice(model, res["chosen"])
    hint = hint_from_decisions(model, decisions)
    assert hint == res["chosen"]
    assert hint_is_feasible(model, hint)
    assert evaluate(model, hint, canonical_levels(model)) == res["vector"]
    # unknown plans are ignored, missing plans and actions outside the limits fall back to keep
    partial = [{"pid": "Z999", "kind": "cancel", "delta": 0}, {"pid": plans[0].pid, "kind": "freq", "delta": 9}]
    fallback = hint_from_decisions(model, partial)
    assert fallback == [vars_of_plan[0] for vars_of_plan in model.plan_vars]
    assert all(model.option_of(v).kind == "keep" for v in fallback)


def test_hint_infeasibility_is_detected() -> None:
    a = Plan("A001", "A", 0, 10, 0, 5, 60, 3)
    b = Plan("B001", "B", 0, 10, 0, 5, 60, 3)
    model = _model([a, b], Limits(fmax=10, tmax=5))
    keep_both = [vars_of_plan[0] for vars_of_plan in model.plan_vars]
    assert not hint_is_feasible(model, keep_both)
    cancel_b = [model.plan_vars[0][0], next(v for v in model.plan_vars[1] if model.option_of(v).kind == "cancel")]
    assert hint_is_feasible(model, cancel_b)


def test_highs_levels_are_independent_of_earlier_time_limits() -> None:
    # every level gets a fresh solver, so a tiny LP limit on one level cannot starve the following ones
    plans = tiny_instance(32, n_plans=6)
    model = _model(plans, Limits(fmax=2, tmax=1))
    levels = canonical_levels(model)
    res = solve_lexicographic_cpsat(model, levels, seed=1, workers=2, time_limit=60)
    highs = solve_lexicographic_highs(
        model, levels, seed=1, threads=2, time_limit=60, reference=res["vector"], hint=res["chosen"], lp_time_limit=60
    )
    assert highs["agrees_with_reference"] and highs["all_optimal"] and highs["vector"] == res["vector"]
    assert all(e.get("lp_status") == "Optimal" for e in highs["levels"])
