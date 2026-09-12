"""Problem D stages: validate, detect (Q1), resolve (Q2), pack (Q3), resolve_interval (Q4), bench,
sensitivity, results; figures and tables live in ``pipelines.d.report`` (imported here so they register).

Conventions (docs/ENGINEERING_STANDARD.md): every stage is ``@stage(name, deps=(...))`` returning
JSON-serialisable metrics; outputs go only to ``ctx.out(...)``; paper numbers via ``ctx.number``;
randomness only via ``ctx.seed_everything``; every optimisation result is re-checked by
``pipelines.d.validators`` before it is written.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from forge.context import StageContext
from forge.runner import stage
from forge.xlsx import write_result
from pipelines.common.validation import run_validation
from pipelines.d import validators
from pipelines.d.contracts import INPUT_CONTRACTS
from pipelines.d.detect import conflict_records, detect_bandsweep, detect_pairwise, graph_stats, overlapping_uses
from pipelines.d.pack import (
    C_TEMPLATE,
    candidate_placements,
    cell_rows,
    greedy_pack,
    highs_pack,
    occupancy_grid,
    plans_from_choice,
    repack_existing,
    solve_pack_cpsat,
    template_span,
)
from pipelines.d.plans import CATEGORIES, Plan, horizon, load_plans, plan_from_record
from pipelines.d.resolve import (
    Limits,
    build_cell_model,
    canonical_levels,
    decisions_from_choice,
    enumerate_options,
    evaluate,
    hint_from_decisions,
    hint_is_feasible,
    scheme_levels,
    solve_lexicographic_cpsat,
    solve_lexicographic_highs,
    solve_weighted_cpsat,
    strengthen,
    table_from_decisions,
)
from pipelines.d.synth import exhaustive_lexicographic, synthetic_instance, tiny_instance

PARQUET = "附件1__Sheet1.parquet"
Q2_LIMITS = Limits(fmax=10, tmax=5)
Q4_LIMITS = Limits(fmax=10, tmax=5, gmax=10, gap_categories=("C",))
PASS = "通过"
FAIL = "未通过"
# incumbents of an earlier verified run, used only as warm starts (configs/hints/*.json carry their provenance)
Q2_HINT = "configs/hints/q2_decisions.json"


def _limit_list(limit: Any, n: int) -> list[float]:
    """Per-level time limits as a list of length ``n`` (a scalar is repeated, a short list is padded)."""
    values = [float(limit)] * n if isinstance(limit, int | float) else [float(x) for x in limit]
    return (values + [values[-1]] * n)[:n]


def _vector_text(vec: list[int] | None) -> str:
    return "(" + ", ".join(str(v) for v in vec) + ")" if vec else "-"


def _max_independent_set(
    n: int, edges: list[tuple[int, int]], *, seed: int, time_limit: float = 60.0
) -> dict[str, Any]:
    """Independence number alpha(G) of the conflict graph, by CP-SAT.

    Two conflicting plans can never both be kept unchanged, so the kept set is independent in G; hence
    ``|keep| <= alpha(G)`` and at least ``n - alpha(G)`` plans must be adjusted or cancelled in *any*
    conflict-free resolution. This bound uses only the conflict graph, so it is independent of the
    resolution model and of the action limits (Proposition on the touched-plan bound)."""
    from ortools.sat.python import cp_model

    cp = cp_model.CpModel()
    x = [cp.NewBoolVar(f"x{i}") for i in range(n)]
    for i, j in edges:
        cp.AddAtMostOne([x[i], x[j]])
    cp.Maximize(sum(x))
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_workers = 8
    solver.parameters.max_time_in_seconds = float(time_limit)
    status = solver.Solve(cp)
    return {
        "value": round(solver.ObjectiveValue()) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0,
        "bound": float(solver.BestObjectiveBound()),
        "status": solver.StatusName(status),
        "members": [i for i in range(n) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and solver.Value(x[i])],
    }


def _load_plans(ctx: StageContext) -> list[Plan]:
    return load_plans(ctx.dep("ingest") / "data" / PARQUET)


def _records(plans: list[Plan]) -> list[dict[str, Any]]:
    return [p.record() for p in plans]


def _plans(records: list[dict[str, Any]]) -> list[Plan]:
    return [plan_from_record(r) for r in records]


@stage("validate", deps=("ingest",), description="Validate the 150 frequency-use plans against their contract")
def validate(ctx: StageContext) -> dict[str, Any]:
    return run_validation(ctx, INPUT_CONTRACTS)


# ----------------------------------------------------------------------------------------------- Q1
@stage("detect", deps=("ingest", "validate"), description="Q1: exact conflict detection with two algorithms")
def detect(ctx: StageContext) -> dict[str, Any]:
    plans = _load_plans(ctx)
    t0 = time.perf_counter()
    pairs = detect_pairwise(plans)
    t_pairwise = time.perf_counter() - t0
    t0 = time.perf_counter()
    sweep = detect_bandsweep(plans)
    t_sweep = time.perf_counter() - t0
    if pairs != sweep:
        raise RuntimeError(f"detectors disagree: pairwise {len(pairs)} vs sweep {len(sweep)}")
    records = conflict_records(plans, pairs)
    stats = graph_stats(plans, pairs)
    use_pairs = sum(r["use_pairs"] for r in records)
    horizon_t = horizon(plans)
    grid = occupancy_grid(plans, horizon_t)
    import numpy as np

    counts = np.zeros(grid.shape, dtype=int)
    for p in plans:
        for start, end in p.uses():
            counts[p.f : p.f_end, start:end] += 1
    validation = validators.validate_detection(plans, [(r["id1"], r["id2"]) for r in records])
    if not validation["ok"]:
        raise RuntimeError(f"independent detection check failed: {validation}")
    multiplicity = {
        str(k): int(sum(1 for r in records if r["use_pairs"] == k)) for k in sorted({r["use_pairs"] for r in records})
    }
    by_id = {p.pid: p for p in plans}
    conflict_uses: set[tuple[str, int]] = set()
    for rec in records:
        a, b = by_id[rec["id1"]], by_id[rec["id2"]]
        for k, m in overlapping_uses(a, b):
            conflict_uses.add((a.pid, k))
            conflict_uses.add((b.pid, m))
    alpha = _max_independent_set(len(plans), [(i, j) for i, j in pairs], seed=ctx.seed("detect-mis"))
    top_degree_max = max((r["degree"] for r in stats["top_degree"]), default=0)
    top_degree_ids = [str(r["pid"]) for r in stats["top_degree"] if r["degree"] == top_degree_max]
    stats.update(
        {
            "use_pairs": int(use_pairs),
            "use_pair_multiplicity": multiplicity,
            "uses_total": int(sum(p.n for p in plans)),
            "uses_in_conflict": len(conflict_uses),
            "isolated_plans": int(len(plans) - stats["plans_involved"]),
            "top_degree_ids": top_degree_ids,
            "max_independent_set": alpha,
            "horizon": int(horizon_t),
            "cells_total": int(counts.size),
            "cells_occupied": int((counts >= 1).sum()),
            "cells_overlap": int((counts >= 2).sum()),
            "cells_max_multiplicity": int(counts.max()),
            "cells_by_cat": {c: int(sum(p.n_cells for p in plans if p.cat == c)) for c in CATEGORIES},
            "seconds_pairwise": t_pairwise,
            "seconds_sweep": t_sweep,
            "detectors_agree": True,
            "pair_multiplicity_max": max((r["use_pairs"] for r in records), default=0),
        }
    )
    ctx.write_json("plans.json", _records(plans))
    ctx.write_json("conflicts.json", records)
    ctx.write_json("stats.json", stats)
    ctx.write_json("validation_report.json", validation)
    ctx.number("QonePlans", len(plans))
    ctx.number("QoneConflictPairs", stats["pairs"])
    for key, value in stats["by_pair"].items():
        ctx.number(f"QoneConflictPairs{key}", value)
    ctx.number("QonePlansInConflict", stats["plans_involved"])
    for c in CATEGORIES:
        ctx.number(f"QonePlansInConflict{c}", stats["plans_involved_by_cat"][c])
    ctx.number("QoneComponents", stats["components"])
    ctx.number("QoneLargestComponent", stats["largest_component"])
    ctx.number("QoneMaxDegree", stats["max_degree"])
    ctx.number("QoneMeanDegree", stats["mean_degree"], ".2f")
    ctx.number("QoneDensity", stats["density"], ".4f")
    ctx.number("QoneUsePairs", use_pairs)
    ctx.number("QoneUsesTotal", stats["uses_total"])
    ctx.number("QoneConflictUses", stats["uses_in_conflict"])
    ctx.number("QoneIsolatedPlans", stats["isolated_plans"])
    ctx.number("QoneHorizon", horizon_t)
    ctx.number("QoneCellsTotal", stats["cells_total"])
    ctx.number("QoneCellsOccupied", stats["cells_occupied"])
    ctx.number("QoneCellsOverlap", stats["cells_overlap"])
    ctx.number("QoneOccupancyPercent", 100.0 * stats["cells_occupied"] / stats["cells_total"], ".1f")
    ctx.number("QonePairwiseMs", 1000 * t_pairwise, ".0f")
    ctx.number("QoneSweepMs", 1000 * t_sweep, ".0f")
    ctx.number("QoneValidator", PASS)
    ctx.number("QoneTopDegreeId", stats["top_degree"][0]["pid"] if stats["top_degree"] else "-")
    ctx.number("QoneTopDegreeIds", "、".join(top_degree_ids))
    ctx.number("QoneTopDegreeCount", len(top_degree_ids))
    ctx.number("QoneMaxIndependentSet", alpha["value"])
    ctx.number("QoneMaxIndependentSetStatus", alpha["status"])
    ctx.number("QoneMinTouched", len(plans) - alpha["value"])
    ctx.log.info("detect.done", pairs=stats["pairs"], by_pair=stats["by_pair"], seconds=t_pairwise)
    return {"pairs": stats["pairs"], "by_pair": stats["by_pair"], "use_pairs": use_pairs, "validator_ok": True}


# ------------------------------------------------------------------------------------------ Q2 / Q4
def _shift_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    freq = [abs(d["delta"]) for d in decisions if d["kind"] == "freq"]
    tim = [abs(d["delta"]) for d in decisions if d["kind"] == "time"]
    gap = [abs(d["delta"]) for d in decisions if d["kind"] == "gap"]

    def stat(xs: list[int]) -> dict[str, Any]:
        return {"count": len(xs), "mean": (sum(xs) / len(xs)) if xs else 0.0, "max": max(xs, default=0), "sum": sum(xs)}

    return {
        "freq": stat(freq),
        "time": stat(tim),
        "gap": stat(gap),
        "cancel": sum(1 for d in decisions if d["kind"] == "cancel"),
    }


def _read_decisions(path: Path) -> list[dict[str, Any]]:
    """Decisions from a stage output (a list) or an in-repo incumbent file ({"provenance", "decisions"})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("decisions", [])) if isinstance(data, dict) else list(data)


def _load_hint(ctx: StageContext, model: Any, source: str | None) -> tuple[list[int] | None, dict[str, Any]]:
    """Warm start (MDR-0004 addendum): ``source`` is a path relative to the run directory or to the repository.

    Returns the hint (one variable per plan) and a small provenance record; a missing file means no hint."""
    if not source:
        return None, {"source": None}
    for path in (ctx.run_dir / source, ctx.repo / source):
        if path.exists():
            decisions = _read_decisions(path)
            hint = hint_from_decisions(model, decisions)
            info = {
                "source": source,
                "path": str(path),
                "feasible": hint_is_feasible(model, hint),
                "vector": evaluate(model, hint, canonical_levels(model)),
            }
            ctx.log.info("hint.loaded", **info)
            return hint, info
    ctx.log.warn("hint.missing", source=source)
    return None, {"source": source, "path": None}


def _run_resolution(
    ctx: StageContext, plans: list[Plan], limits: Limits, prefix: str, *, default_hint: str | None = None
) -> dict[str, Any]:
    """Shared Q2/Q4 pipeline: model, lexicographic CP-SAT, cross-checks, alternatives, validation, outputs."""
    workers = int(ctx.param("workers", 8))
    level_limits = ctx.param("level_time_limits", None) or float(ctx.param("time_limit", 360))
    highs_limit = float(ctx.param("highs_time_limit", 120))
    weighted_limit = float(ctx.param("weighted_time_limit", 180))
    alt_limit = float(ctx.param("alt_time_limit", 60))
    seed = ctx.seed_everything(prefix)
    options = [enumerate_options(p, limits) for p in plans]
    t0 = time.perf_counter()
    model = build_cell_model(plans, options)
    strength = strengthen(model) if bool(ctx.param("strengthen", True)) else None
    build_seconds = time.perf_counter() - t0
    levels = canonical_levels(model)
    ctx.log.info(
        "model.built",
        vars=model.n_vars,
        rows=len(model.rows),
        rows_raw=model.n_rows_raw,
        groups=len(strength.groups) if strength else 0,
        forced=len(strength.forced) if strength else 0,
        seconds=build_seconds,
    )

    hint, hint_info = _load_hint(ctx, model, ctx.param("hint_from", default_hint))
    # The separated-weight scalarisation runs first (MDR-0009): warm-started from the *file* incumbent it is an
    # independent second search, and its solution seeds the lexicographic pass, so the reported vector can
    # never be worse than either route. (Previously it was hinted by the lexicographic solution — circular.)
    weighted = solve_weighted_cpsat(
        model, levels, seed=seed, workers=workers, time_limit=weighted_limit, hint=hint, strength=strength
    )
    start = hint
    if weighted["chosen"] is not None and hint_is_feasible(model, weighted["chosen"]):
        if hint is None or list(weighted["vector"]) < evaluate(model, hint, levels):
            start = weighted["chosen"]
    hint_info["start_from"] = "file" if start is hint else "weighted"
    hint_info["start_vector"] = evaluate(model, start, levels) if start is not None else None
    primary = solve_lexicographic_cpsat(
        model, levels, seed=seed, workers=workers, time_limit=level_limits, strength=strength, hint=start
    )
    ctx.log.info("cpsat.primary", vector=primary["vector"], levels=primary["levels"], seconds=primary["seconds"])
    if primary["chosen"] is None or len(primary["vector"]) != len(levels):
        raise RuntimeError(f"CP-SAT found no complete solution: {primary['levels']}")
    if bool(ctx.param("require_optimal", False)) and not primary["all_optimal"]:
        raise RuntimeError(f"CP-SAT did not prove optimality on every level: {primary['levels']}")
    deterministic: bool | None = None
    if bool(ctx.param("repeat", False)):
        repeat = solve_lexicographic_cpsat(
            model, levels, seed=seed, workers=workers, time_limit=level_limits, strength=strength
        )
        deterministic = repeat["chosen"] == primary["chosen"] and repeat["vector"] == primary["vector"]
    weighted_agree = weighted["vector"] == primary["vector"]
    ctx.log.info(
        "cpsat.weighted",
        vector=weighted["vector"],
        status=weighted["status"],
        agree=weighted_agree,
        start_from=hint_info["start_from"],
    )
    highs = solve_lexicographic_highs(
        model,
        levels,
        seed=seed,
        threads=workers,
        time_limit=highs_limit,
        reference=primary["vector"],
        hint=primary["chosen"],
        strength=strength,
        lp_time_limit=float(ctx.param("lp_time_limit", highs_limit)),
    )
    highs_agree = highs["agrees_with_reference"]
    ctx.log.info("highs.done", levels=highs["levels"], all_optimal=highs["all_optimal"], seconds=highs["seconds"])

    decisions = decisions_from_choice(model, primary["chosen"])
    table = table_from_decisions(decisions)
    validation = validators.validate_resolution(
        plans,
        decisions,
        fmax=limits.fmax,
        tmax=limits.tmax,
        gmax=limits.gmax,
        gap_categories=limits.gap_categories,
        horizon_cap=limits.horizon_cap,
        reported_table=table,
        reported_vector=primary["vector"],
    )
    if not validation["ok"]:
        raise RuntimeError(f"independent validation failed: {validation['errors']}")
    survivors = [plan_from_record(d["plan"]) for d in decisions if d["plan"] is not None]

    # --- objective schemes (MDR-0003). Every scheme gets the same per-level budget, and every scheme is
    # warm-started from the lexicographically best solution known for *its own* levels among all solutions
    # found so far (MDR-0013). With the incumbent cut of MDR-0009 this makes the reported vector of each
    # scheme at least as good as every other scheme's solution evaluated under it, so no scheme can be
    # left reporting a point that another row of the same table already dominates.
    scheme_names = ("P", "T", "S", "W")
    alternatives: dict[str, Any] = {}
    alt_decisions_out: dict[str, Any] = {}
    pool: list[list[int]] = [list(primary["chosen"])]

    def _best_for(name: str) -> list[int]:
        lv = scheme_levels(name, model)
        return min(pool, key=lambda c: evaluate(model, c, lv))

    def _record(name: str, res: dict[str, Any], chosen: list[int] | None, budget: float) -> None:
        alt_decisions = decisions_from_choice(model, chosen) if chosen else []
        alt_valid = (
            validators.validate_resolution(
                plans,
                alt_decisions,
                fmax=limits.fmax,
                tmax=limits.tmax,
                gmax=limits.gmax,
                gap_categories=limits.gap_categories,
                horizon_cap=limits.horizon_cap,
            )
            if chosen
            else {"ok": False}
        )
        alternatives[name] = {
            "scheme_vector": res["vector"],
            "canonical_vector": evaluate(model, chosen, levels) if chosen else None,
            "table": table_from_decisions(alt_decisions) if chosen else None,
            "all_optimal": res["all_optimal"],
            "levels": res["levels"],
            "n_levels": len(scheme_levels(name, model)),
            "seconds": res["seconds"],
            "budget_seconds": budget,
            "validator_ok": bool(alt_valid["ok"]),
            "shifts": _shift_stats(alt_decisions),
        }
        alt_decisions_out[name] = alt_decisions
        ctx.log.info(
            "alternative", scheme=name, vector=alternatives[name]["canonical_vector"], optimal=res["all_optimal"]
        )

    for name in scheme_names:
        if name == "P":
            _record("P", primary, primary["chosen"], sum(_limit_list(level_limits, len(levels))))
            continue
        lv = scheme_levels(name, model)
        res = solve_lexicographic_cpsat(
            model, lv, seed=seed, workers=workers, time_limit=alt_limit, hint=_best_for(name), strength=strength
        )
        if res["chosen"]:
            pool.append(list(res["chosen"]))
        _record(name, res, res["chosen"], alt_limit * len(lv))
    # repair round: any scheme whose reported point is beaten by a solution found later is re-solved from it
    for name in scheme_names[1:]:
        lv = scheme_levels(name, model)
        best = _best_for(name)
        if evaluate(model, best, lv) < list(alternatives[name]["scheme_vector"]):
            res = solve_lexicographic_cpsat(
                model, lv, seed=seed, workers=workers, time_limit=alt_limit, hint=best, strength=strength
            )
            if res["chosen"]:
                pool.append(list(res["chosen"]))
            _record(name, res, res["chosen"], alternatives[name]["budget_seconds"] + alt_limit * len(lv))
            ctx.log.info("alternative.repaired", scheme=name, vector=alternatives[name]["canonical_vector"])

    # --- conditional optimality (MDR-0012). Fixing the *set* of cancelled plans to the one reported above
    # turns the remaining levels into a restricted problem that CP-SAT can close; a bound proved here bounds
    # the restriction only, never the unrestricted lexicographic optimum.
    conditional: dict[str, Any] = {}
    cond_limits = ctx.param("conditional_time_limits", None)
    if cond_limits:
        fix_vars: dict[int, int] = {}
        for i, chosen_v in enumerate(primary["chosen"]):
            cancel_v = next(v for v in model.plan_vars[i] if model.option_of(v).kind == "cancel")
            fix_vars[cancel_v] = int(chosen_v == cancel_v)
        cond = solve_lexicographic_cpsat(
            model,
            levels[3:],
            seed=seed,
            workers=workers,
            time_limit=[float(x) for x in cond_limits],
            hint=primary["chosen"],
            strength=strength,
            fix_vars=fix_vars,
        )
        cond_decisions = decisions_from_choice(model, cond["chosen"]) if cond["chosen"] else []
        cond_valid = (
            validators.validate_resolution(
                plans,
                cond_decisions,
                fmax=limits.fmax,
                tmax=limits.tmax,
                gmax=limits.gmax,
                gap_categories=limits.gap_categories,
                horizon_cap=limits.horizon_cap,
            )
            if cond_decisions
            else {"ok": False}
        )
        conditional = {
            "fixed_cancelled": sorted(d["pid"] for d in decisions if d["kind"] == "cancel"),
            "levels": cond["levels"],
            "vector": cond["vector"],
            "canonical_vector": evaluate(model, cond["chosen"], levels) if cond["chosen"] else None,
            "all_optimal": cond["all_optimal"],
            "seconds": cond["seconds"],
            "validator_ok": bool(cond_valid["ok"]),
        }
        ctx.log.info("conditional", vector=cond["vector"], all_optimal=cond["all_optimal"])

    shifts = _shift_stats(decisions)
    report = {
        "limits": limits.__dict__,
        "model": {
            "vars": model.n_vars,
            "rows": len(model.rows),
            "rows_raw": model.n_rows_raw,
            "cells": model.n_cells,
            "memberships": model.memberships,
            "horizon": model.horizon,
            "options_per_plan": {
                c: max(len(options[i]) for i, p in enumerate(plans) if p.cat == c) for c in CATEGORIES
            },
            "build_seconds": build_seconds,
            "strengthening_groups": len(strength.groups) if strength else 0,
            "forced_cancel_pairs": len(strength.forced) if strength else 0,
            "interacting_pairs": strength.interacting_pairs if strength else None,
        },
        "primary": {k: v for k, v in primary.items() if k != "chosen"},
        "hint": hint_info,
        "all_optimal": primary["all_optimal"],
        "repeat_deterministic": deterministic,
        "weighted": {k: v for k, v in weighted.items() if k != "chosen"},
        "weighted_agree": weighted_agree,
        "highs": {k: v for k, v in highs.items() if k != "chosen"},
        "highs_agree": highs_agree,
        "vector": primary["vector"],
        "table": table,
        "shifts": shifts,
        "amplitude_normalised": primary["vector"][-1] / 10.0,
        "horizon_after": horizon(survivors),
        "conditional": conditional,
    }
    ctx.write_json("decisions.json", decisions)
    ctx.write_json("resolved_plans.json", _records(survivors))
    ctx.write_json("solver_report.json", report)
    ctx.write_json("alternatives.json", alternatives)
    ctx.write_json("alternative_decisions.json", alt_decisions_out)
    ctx.write_json("validation_report.json", validation)

    for c in CATEGORIES:
        ctx.number(f"{prefix}Keep{c}", table[c]["keep"])
        ctx.number(f"{prefix}Adjust{c}", table[c]["adjust"])
        ctx.number(f"{prefix}Cancel{c}", table[c]["cancel"])
    ctx.number(f"{prefix}KeepTotal", sum(table[c]["keep"] for c in CATEGORIES))
    ctx.number(f"{prefix}AdjustTotal", sum(table[c]["adjust"] for c in CATEGORIES))
    ctx.number(f"{prefix}CancelTotal", sum(table[c]["cancel"] for c in CATEGORIES))
    ctx.number(f"{prefix}RemainingPlans", len(survivors))
    ctx.number(f"{prefix}HorizonCap", limits.horizon_cap if limits.horizon_cap else "无")
    ctx.number(f"{prefix}FreqShifted", shifts["freq"]["count"])
    ctx.number(f"{prefix}TimeShifted", shifts["time"]["count"])
    ctx.number(f"{prefix}GapChanged", shifts["gap"]["count"])
    ctx.number(f"{prefix}MeanAbsFreqShift", shifts["freq"]["mean"], ".2f")
    ctx.number(f"{prefix}MaxAbsFreqShift", shifts["freq"]["max"])
    ctx.number(f"{prefix}SumAbsFreqShift", shifts["freq"]["sum"])
    ctx.number(f"{prefix}MeanAbsTimeShift", shifts["time"]["mean"], ".2f")
    ctx.number(f"{prefix}MaxAbsTimeShift", shifts["time"]["max"])
    ctx.number(f"{prefix}SumAbsTimeShift", shifts["time"]["sum"])
    ctx.number(f"{prefix}MeanAbsGapChange", shifts["gap"]["mean"], ".2f")
    ctx.number(f"{prefix}MaxAbsGapChange", shifts["gap"]["max"])
    ctx.number(f"{prefix}Amplitude", primary["vector"][-1] / 10.0, ".1f")
    ctx.number(f"{prefix}AmplitudeScaled", primary["vector"][-1])
    ctx.number(f"{prefix}Vars", model.n_vars)
    ctx.number(f"{prefix}Rows", len(model.rows))
    ctx.number(f"{prefix}RowsRaw", model.n_rows_raw)
    ctx.number(f"{prefix}Memberships", model.memberships)
    ctx.number(f"{prefix}Cells", model.n_cells)
    ctx.number(f"{prefix}CpsatSeconds", primary["seconds"], ".1f")
    ctx.number(f"{prefix}HighsSeconds", highs["seconds"], ".1f")
    ctx.number(f"{prefix}WeightedSeconds", weighted["seconds"], ".1f")
    ctx.number(f"{prefix}HighsAgree", PASS if highs_agree else FAIL)
    ctx.number(f"{prefix}HighsAllOptimal", PASS if highs["all_optimal"] else FAIL)
    ctx.number(f"{prefix}WeightedAgree", PASS if weighted_agree else FAIL)
    ctx.number(f"{prefix}AllOptimal", PASS if primary["all_optimal"] else FAIL)
    ctx.number(f"{prefix}Deterministic", "未检验" if deterministic is None else (PASS if deterministic else FAIL))
    ctx.number(f"{prefix}ForcedCancelPairs", len(strength.forced) if strength else 0)
    ctx.number(f"{prefix}InteractingPairs", strength.interacting_pairs if strength else 0)
    ctx.number(f"{prefix}Groups", len(strength.groups) if strength else 0)
    for entry in primary["levels"]:
        key = entry["level"].capitalize()
        ctx.number(f"{prefix}Value{key}", entry.get("value", "-"))
        ctx.number(f"{prefix}Bound{key}", math.ceil(entry.get("bound", 0) - 1e-6) if "bound" in entry else "-")
        ctx.number(f"{prefix}Status{key}", entry.get("status", "-"))
    ctx.number(f"{prefix}Validator", PASS if validation["ok"] else FAIL)
    ctx.number(f"{prefix}HorizonAfter", report["horizon_after"])
    ctx.number(f"{prefix}HintUsed", "是" if hint is not None else "否")
    ctx.number(f"{prefix}HintFeasible", PASS if hint_info.get("feasible") else FAIL)
    ctx.number(f"{prefix}HintVector", _vector_text(hint_info.get("vector")))
    hint_vec = hint_info.get("vector")
    ctx.number(
        f"{prefix}HintImproved",
        "未使用提示" if hint_vec is None else ("严格改进" if list(primary["vector"]) < list(hint_vec) else "未改进"),
    )
    ctx.number(f"{prefix}StartVector", _vector_text(hint_info.get("start_vector")))
    ctx.number(f"{prefix}Vector", _vector_text(primary["vector"]))
    ctx.number(f"{prefix}Levels", len(levels))
    for entry in highs["levels"]:
        if "lp_value" in entry:
            ctx.number(f"{prefix}LpBound{entry['level'].capitalize()}", entry["lp_value"], ".2f")
    for name, alt in alternatives.items():
        vec = alt["canonical_vector"]
        ctx.number(f"{prefix}Scheme{name}Seconds", alt["seconds"], ".1f")
        ctx.number(f"{prefix}Scheme{name}Budget", alt["budget_seconds"], ".0f")
        if vec is not None:
            ctx.number(f"{prefix}Scheme{name}AdjustTotal", sum(vec[3:6]))
            ctx.number(f"{prefix}Scheme{name}CancelTotal", sum(vec[0:3]))
            ctx.number(f"{prefix}Scheme{name}Amplitude", vec[6] / 10.0, ".1f")
            ctx.number(f"{prefix}Scheme{name}AdjustA", vec[3])
    if conditional:
        for entry in conditional["levels"]:
            key = entry["level"].capitalize()
            ctx.number(f"{prefix}CondValue{key}", entry.get("value", "-"))
            ctx.number(f"{prefix}CondBound{key}", math.ceil(entry.get("bound", 0) - 1e-6) if "bound" in entry else "-")
            ctx.number(f"{prefix}CondStatus{key}", entry.get("status", "-"))
        ctx.number(f"{prefix}CondAllOptimal", PASS if conditional["all_optimal"] else FAIL)
        ctx.number(f"{prefix}CondSeconds", conditional["seconds"], ".0f")
        ctx.number(f"{prefix}CondCancelled", len(conditional["fixed_cancelled"]))
        ctx.number(f"{prefix}CondValidator", PASS if conditional["validator_ok"] else FAIL)
    return {
        "vector": primary["vector"],
        "table": table,
        "all_optimal": primary["all_optimal"],
        "deterministic": deterministic,
        "weighted_agree": weighted_agree,
        "highs_agree": highs_agree,
        "validator_ok": validation["ok"],
        "cpsat_seconds": primary["seconds"],
        "highs_seconds": highs["seconds"],
        "horizon_after": report["horizon_after"],
        "conditional_all_optimal": conditional.get("all_optimal"),
    }


@stage("resolve", deps=("detect",), description="Q2: lexicographic conflict resolution (CP-SAT, HiGHS cross-check)")
def resolve(ctx: StageContext) -> dict[str, Any]:
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    limits = Limits(fmax=int(ctx.param("fmax", Q2_LIMITS.fmax)), tmax=int(ctx.param("tmax", Q2_LIMITS.tmax)))
    return _run_resolution(ctx, plans, limits, "Qtwo", default_hint=Q2_HINT)


@stage(
    "resolve_interval",
    deps=("detect",),
    description="Q4: resolution with C-class gap adjustments (|dg| <= 10) as an additional single-parameter action",
)
def resolve_interval(ctx: StageContext) -> dict[str, Any]:
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    # "no extra time-frequency resource" (MDR-0011): the resource region is the one the original plans
    # already span, [0,100) x [0,T_end); an action that pushes a plan's last use past T_end is illegal.
    cap = int(ctx.param("horizon_cap", horizon(plans)))
    limits = Limits(
        fmax=int(ctx.param("fmax", Q4_LIMITS.fmax)),
        tmax=int(ctx.param("tmax", Q4_LIMITS.tmax)),
        gmax=int(ctx.param("gmax", Q4_LIMITS.gmax)),
        gap_categories=("C",),
        horizon_cap=cap,
    )
    out = _run_resolution(ctx, plans, limits, "Qfour", default_hint=Q2_HINT)
    # Unrestricted variant (MDR-0011): the same action set without the cap, warm-started from the capped
    # solution. Because the capped solution is feasible there too, the incumbent cut of MDR-0009 makes the
    # variant's reported vector no worse than the capped one; whether it is strictly better answers
    # "does the cap cost anything?" without leaving the run.
    free_limits = ctx.param("variant_time_limits", None)
    if free_limits:
        seed = ctx.seed("Qfour-uncapped")
        open_limits = Limits(fmax=limits.fmax, tmax=limits.tmax, gmax=limits.gmax, gap_categories=("C",))
        options = [enumerate_options(p, open_limits) for p in plans]
        model = build_cell_model(plans, options)
        levels = canonical_levels(model)
        decisions = json.loads(ctx.out("decisions.json").read_text(encoding="utf-8"))
        hint = hint_from_decisions(model, decisions)
        res = solve_lexicographic_cpsat(
            model,
            levels,
            seed=seed,
            workers=int(ctx.param("workers", 8)),
            time_limit=[float(x) for x in free_limits],
            hint=hint,
            strength=strengthen(model),
        )
        var_decisions = decisions_from_choice(model, res["chosen"]) if res["chosen"] else []
        var_valid = (
            validators.validate_resolution(
                plans, var_decisions, fmax=limits.fmax, tmax=limits.tmax, gmax=limits.gmax, gap_categories=("C",)
            )
            if var_decisions
            else {"ok": False}
        )
        survivors = [plan_from_record(d["plan"]) for d in var_decisions if d["plan"] is not None]
        variant = {
            "limits": open_limits.__dict__,
            "vector": res["vector"],
            "levels": res["levels"],
            "table": table_from_decisions(var_decisions) if var_decisions else None,
            "all_optimal": res["all_optimal"],
            "seconds": res["seconds"],
            "vars": model.n_vars,
            "rows": len(model.rows),
            "horizon_after": horizon(survivors),
            "validator_ok": bool(var_valid["ok"]),
            "strictly_better": list(res["vector"]) < list(out["vector"]),
            "same_as_capped": list(res["vector"]) == list(out["vector"]),
        }
        if not var_valid["ok"]:
            raise RuntimeError(f"unrestricted Q4 variant failed validation: {var_valid['errors']}")
        ctx.write_json("variant_uncapped.json", variant)
        ctx.number("QfourFreeVector", _vector_text(res["vector"]))
        ctx.number("QfourFreeCancelTotal", sum(res["vector"][0:3]))
        ctx.number("QfourFreeAdjustTotal", sum(res["vector"][3:6]))
        ctx.number("QfourFreeHorizon", variant["horizon_after"])
        ctx.number("QfourFreeVars", model.n_vars)
        ctx.number("QfourFreeSeconds", res["seconds"], ".0f")
        ctx.number("QfourFreeStrictlyBetter", PASS if variant["strictly_better"] else FAIL)
        ctx.number("QfourFreeSameAsCapped", PASS if variant["same_as_capped"] else FAIL)
        ctx.number("QfourFreeValidator", PASS)
        ctx.log.info("q4.variant", vector=res["vector"], horizon=variant["horizon_after"])
        out["variant_vector"] = res["vector"]
    return out


@stage(
    "coldstart",
    deps=("detect", "resolve"),
    description="Q2 solved from scratch (no stored incumbent), so that the reported result does not depend on it",
)
def coldstart(ctx: StageContext) -> dict[str, Any]:
    """Answers the reviewer's question 'is the repository's answer the search's output, or its input?'.

    The primary ``resolve`` stage warm-starts from ``configs/hints/q2_decisions.json`` (an incumbent of an
    earlier run, provenance inside the file). This stage runs the identical model and objective with the
    hint switched off, and reports the vector it reaches on its own together with the difference. Nothing
    here feeds the delivered workbooks; it is evidence about the method, not about the answer."""
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    limits = Limits(fmax=int(ctx.param("fmax", Q2_LIMITS.fmax)), tmax=int(ctx.param("tmax", Q2_LIMITS.tmax)))
    ctx.params.setdefault("hint_from", "")
    out = _run_resolution(ctx, plans, limits, "Cold", default_hint=None)
    warm = ctx.dep_data("resolve", "solver_report.json")
    cold_vec, warm_vec = list(out["vector"]), list(warm["vector"])
    ctx.number("ColdMatchesWarm", PASS if cold_vec == warm_vec else FAIL)
    ctx.number("ColdWarmVector", _vector_text(warm_vec))
    ctx.number(
        "ColdRelation",
        "相同" if cold_vec == warm_vec else ("冷启动更优" if cold_vec < warm_vec else "冷启动更差"),
    )
    ctx.number("ColdCancelDelta", sum(cold_vec[0:3]) - sum(warm_vec[0:3]))
    ctx.number("ColdAdjustDelta", sum(cold_vec[3:6]) - sum(warm_vec[3:6]))
    ctx.log.info("coldstart", cold=cold_vec, warm=warm_vec)
    return {"cold_vector": cold_vec, "warm_vector": warm_vec, "matches": cold_vec == warm_vec}


@stage(
    "compare",
    deps=("resolve", "resolve_interval"),
    description="Q4 vs Q2: lexicographic comparison of the two resolutions",
)
def compare(ctx: StageContext) -> dict[str, Any]:
    q2 = ctx.dep_data("resolve", "solver_report.json")
    q4 = ctx.dep_data("resolve_interval", "solver_report.json")
    q2_vec, q4_vec = list(q2["vector"]), list(q4["vector"])
    not_worse = q4_vec <= q2_vec  # Q4's action set is a superset of Q2's (MDR-0006)
    comparison = {
        "q2_vector": q2_vec,
        "q4_vector": q4_vec,
        "lexicographically_not_worse": not_worse,
        "cancel_total_delta": sum(q4_vec[0:3]) - sum(q2_vec[0:3]),
        "adjust_total_delta": sum(q4_vec[3:6]) - sum(q2_vec[3:6]),
        "amplitude_delta": (q4_vec[6] - q2_vec[6]) / 10.0,
        "q2_table": q2["table"],
        "q4_table": q4["table"],
        "q2_horizon_after": q2["horizon_after"],
        "q4_horizon_after": q4["horizon_after"],
        "q4_gap_changed": q4["shifts"]["gap"]["count"],
    }
    ctx.write_json("comparison.json", comparison)
    ctx.number("QfourLexNotWorse", PASS if not_worse else FAIL)
    ctx.number("QfourCancelDelta", comparison["cancel_total_delta"])
    ctx.number("QfourAdjustDelta", comparison["adjust_total_delta"])
    ctx.number("QfourAmplitudeDelta", comparison["amplitude_delta"], ".1f")
    ctx.number("QfourHorizonDelta", q4["horizon_after"] - q2["horizon_after"])
    return {"lexicographically_not_worse": not_worse, "q2": q2_vec, "q4": q4_vec}


# ----------------------------------------------------------------------------------------------- Q3
def _pack_once(
    ctx: StageContext,
    existing: list[Plan],
    horizon_t: int,
    *,
    tag: str,
    time_limit: float,
    mip_limit: float,
    lp_limit: float,
) -> dict[str, Any]:
    import numpy as np

    workers = int(ctx.param("workers", 8))
    seed = ctx.seed(f"pack-{tag}")
    grid = occupancy_grid(existing, horizon_t)
    free_cells = int((~grid).sum())
    free_by_band = (~grid).sum(axis=1)
    cells_per_plan = C_TEMPLATE["w"] * C_TEMPLATE["d"] * C_TEMPLATE["n"]
    t0 = time.perf_counter()
    cands = candidate_placements(grid, C_TEMPLATE)
    rows = cell_rows(cands, C_TEMPLATE, horizon_t)
    build_seconds = time.perf_counter() - t0
    greedy = greedy_pack(cands, C_TEMPLATE, grid)
    ctx.log.info(
        "pack.model", tag=tag, candidates=len(cands), rows=len(rows), greedy=len(greedy), seconds=build_seconds
    )
    cp = solve_pack_cpsat(rows, len(cands), hint=greedy, seed=seed, workers=workers, time_limit=time_limit)
    ctx.log.info(
        "pack.cpsat", tag=tag, status=cp["status"], value=cp["value"], bound=cp["bound"], seconds=cp["seconds"]
    )
    lp = (
        highs_pack(rows, len(cands), integer=False, time_limit=lp_limit, seed=seed, threads=workers)
        if lp_limit > 0
        else None
    )
    mip = (
        highs_pack(rows, len(cands), integer=True, time_limit=mip_limit, seed=seed, threads=workers)
        if mip_limit > 0
        else None
    )
    bounds: dict[str, float] = {
        "free_cells": math.floor(free_cells / cells_per_plan),
        "per_band": math.floor(
            sum(int(b) // (C_TEMPLATE["d"] * C_TEMPLATE["n"]) for b in free_by_band) / C_TEMPLATE["w"]
        ),
        "cpsat": math.floor(cp["bound"] + 1e-6) if cp["bound"] is not None else math.inf,
    }
    if lp is not None and lp["status"] == "Optimal":
        bounds["lp"] = math.floor(lp["value"] + 1e-6)
    if mip is not None and mip.get("bound") is not None and math.isfinite(mip["bound"]):
        bounds["highs_mip"] = math.floor(mip["bound"] + 1e-6)
    upper = int(min(bounds.values()))
    best_name, best = "cpsat", cp
    if mip is not None and mip.get("chosen") and len(mip["chosen"]) > cp["value"]:
        best_name, best = "highs_mip", mip
    new_plans = plans_from_choice(cands, best["chosen"], C_TEMPLATE)
    validation = validators.validate_packing(existing, new_plans, horizon=horizon_t, template=C_TEMPLATE)
    if not validation["ok"]:
        raise RuntimeError(f"independent packing validation failed: {validation['errors']}")
    value = len(new_plans)
    return {
        "tag": tag,
        "horizon": int(horizon_t),
        "existing": len(existing),
        "cells_total": int(grid.size),
        "cells_occupied": int(grid.sum()),
        "free_cells": free_cells,
        "candidates": len(cands),
        "rows": len(rows),
        "build_seconds": build_seconds,
        "greedy": len(greedy),
        "cpsat": {k: v for k, v in cp.items() if k != "chosen"},
        "lp": lp,
        "highs_mip": {k: v for k, v in (mip or {}).items() if k != "chosen"} if mip else None,
        "bounds": bounds,
        "upper_bound": upper,
        "value": value,
        "gap": upper - value,
        "optimal": upper == value,
        "source": best_name,
        "utilisation_before": float(grid.sum() / grid.size),
        "utilisation_after": float((grid.sum() + value * cells_per_plan) / grid.size),
        "new_plans": _records(new_plans),
        "validation": validation,
        "free_by_band": [int(b) for b in free_by_band],
        "span": template_span(C_TEMPLATE),
        "seed": seed,
        "np_version": str(np.__version__),
    }


@stage("pack", deps=("detect", "resolve"), description="Q3: maximum number of additional C-class plans (set packing)")
def pack(ctx: StageContext) -> dict[str, Any]:
    existing = _plans(ctx.dep_data("resolve", "resolved_plans.json"))
    original = _plans(ctx.dep_data("detect", "plans.json"))
    horizon_t = horizon(existing)
    result = _pack_once(
        ctx,
        existing,
        horizon_t,
        tag="main",
        time_limit=float(ctx.param("time_limit", 900)),
        mip_limit=float(ctx.param("mip_time_limit", 300)),
        lp_limit=float(ctx.param("lp_time_limit", 300)),
    )
    ctx.write_json("new_plans.json", result["new_plans"])
    ctx.write_json("validation_report.json", result["validation"])
    alternatives: dict[str, Any] = {}
    alt_horizon = horizon(original)
    if bool(ctx.param("alt_horizon", True)) and alt_horizon != horizon_t:
        alt = _pack_once(
            ctx,
            existing,
            alt_horizon,
            tag="original-horizon",
            time_limit=float(ctx.param("alt_time_limit", 240)),
            mip_limit=0,
            lp_limit=float(ctx.param("lp_time_limit", 600)),
        )
        alternatives["original_horizon"] = {k: v for k, v in alt.items() if k not in {"new_plans", "free_by_band"}}
    # MDR-0010 interpretation B: the existing plans may themselves be shifted by an unrestricted amount.
    # A first-fit-decreasing re-placement is one feasible layout, so the number it admits is a valid lower
    # bound on that interpretation's optimum; the free-cell capacity bound is a valid upper bound for both
    # interpretations, because shifting never changes how many cells a plan occupies. Several construction
    # orders are tried and the best is kept — each is feasible, so the maximum is still a valid lower bound.
    if bool(ctx.param("repack", True)):
        best_rep: dict[str, Any] | None = None
        rep_trials: list[dict[str, Any]] = []
        for order, time_first in [
            (o, tf) for o in ctx.param("repack_orders", ["area", "width", "span", "duty"]) for tf in (False, True)
        ]:
            repacked, _ = repack_existing(existing, horizon_t, order=str(order), time_first=bool(time_first))
            moved = sum(1 for a, b in zip(sorted(existing, key=lambda p: p.pid), repacked) if (a.f, a.s) != (b.f, b.s))
            params_kept = all(
                (a.w, a.d, a.g, a.n) == (b.w, b.d, b.g, b.n)
                for a, b in zip(sorted(existing, key=lambda p: p.pid), repacked)
            )
            contained = all(0 <= p.f and p.f_end <= 100 and p.s >= 0 and p.end <= horizon_t for p in repacked)
            if not params_kept or not contained or len(repacked) != len(existing):
                raise RuntimeError("repack changed a plan parameter, dropped a plan, or left the resource region")
            trial = _pack_once(
                ctx,
                repacked,
                horizon_t,
                tag=f"repack-{order}-{'t' if time_first else 'f'}",
                time_limit=float(ctx.param("repack_time_limit", 300)),
                mip_limit=0,
                lp_limit=0,
            )
            trial["order"], trial["time_first"], trial["existing_moved"] = str(order), bool(time_first), moved
            trial["params_kept"] = params_kept
            trial["repacked"] = _records(repacked)
            rep_trials.append({k: v for k, v in trial.items() if k not in {"new_plans", "free_by_band", "repacked"}})
            if best_rep is None or trial["value"] > best_rep["value"]:
                best_rep = trial
        rep = best_rep
        assert rep is not None
        alternatives["repack"] = {
            k: v for k, v in rep.items() if k not in {"new_plans", "free_by_band", "validation", "repacked"}
        } | {"trials": rep_trials, "n_trials": len(rep_trials)}
        ctx.write_json("repack_plans.json", {"existing": rep["repacked"], "new": rep["new_plans"]})
        ctx.log.info("pack.repack", order=rep["order"], moved=rep["existing_moved"], new_plans=rep["value"])
        ctx.number("QthreeAltRepackNewPlans", rep["value"])
        ctx.number("QthreeAltRepackBound", rep["bounds"]["free_cells"])
        ctx.number("QthreeAltRepackMoved", rep["existing_moved"])
        ctx.number("QthreeAltRepackStatus", rep["cpsat"]["status"])
        ctx.number("QthreeAltRepackGreedy", rep["greedy"])
        ctx.number("QthreeAltRepackTrials", len(rep_trials))
        ctx.number("QthreeAltRepackWorst", min(t["value"] for t in rep_trials))
        ctx.number("QthreeAltRepackUtil", 100 * rep["utilisation_after"], ".1f")
        ctx.number("QthreeAltRepackValidator", PASS)
    # Layout sensitivity (MDR-0014): the same packing model on each of the four objective schemes'
    # conflict-free layouts. All four are legitimate answers to Problem 2, so the spread quantifies how
    # conditional Q3's number is on *which* Problem-2 solution it is built upon.
    layout_rows: list[dict[str, Any]] = []
    if bool(ctx.param("layouts", True)):
        alt_decisions = ctx.dep_data("resolve", "alternative_decisions.json")
        for name, decs in sorted(alt_decisions.items()):
            survivors = [plan_from_record(d["plan"]) for d in decs if d.get("plan")]
            if not survivors:
                continue
            h = horizon(survivors)
            res = _pack_once(
                ctx,
                survivors,
                h,
                tag=f"layout-{name}",
                time_limit=float(ctx.param("layout_time_limit", 120)),
                mip_limit=0,
                lp_limit=0,
            )
            layout_rows.append(
                {
                    "scheme": name,
                    "survivors": len(survivors),
                    "cancelled": 150 - len(survivors),
                    "horizon": h,
                    "free_cells": res["free_cells"],
                    "new_plans": res["value"],
                    "bound": res["upper_bound"],
                    "status": res["cpsat"]["status"],
                    "optimal": res["optimal"],
                    "validator_ok": bool(res["validation"]["ok"]),
                }
            )
            ctx.log.info("pack.layout", scheme=name, free=res["free_cells"], new_plans=res["value"])
        ctx.write_json("layouts.json", layout_rows)
        if layout_rows:
            ctx.number("QthreeLayoutCases", len(layout_rows))
            ctx.number("QthreeLayoutMin", min(r["new_plans"] for r in layout_rows))
            ctx.number("QthreeLayoutMax", max(r["new_plans"] for r in layout_rows))
            ctx.number(
                "QthreeLayoutSpreadPercent",
                100.0
                * (max(r["new_plans"] for r in layout_rows) / max(min(r["new_plans"] for r in layout_rows), 1) - 1),
                ".0f",
            )
            ctx.number("QthreeLayoutFreeMin", min(r["free_cells"] for r in layout_rows))
            ctx.number("QthreeLayoutFreeMax", max(r["free_cells"] for r in layout_rows))
            ctx.number(
                "QthreeLayoutFreeSpreadPercent",
                100.0
                * (max(r["free_cells"] for r in layout_rows) / max(min(r["free_cells"] for r in layout_rows), 1) - 1),
                ".1f",
            )
            ctx.number("QthreeLayoutAllValid", PASS if all(r["validator_ok"] for r in layout_rows) else FAIL)
    # capacity of the empty region (what "no extra resource" could hold at most without any existing plan)
    empty_bound = math.floor(100 * horizon_t / (C_TEMPLATE["w"] * C_TEMPLATE["d"] * C_TEMPLATE["n"]))
    report = {k: v for k, v in result.items() if k not in {"new_plans"}}
    report["alternatives"] = alternatives
    report["layouts"] = layout_rows
    report["empty_region_bound"] = empty_bound
    ctx.write_json("pack_report.json", report)
    ctx.number("QthreeNewPlans", result["value"])
    ctx.number("QthreeUpperBound", result["upper_bound"])
    ctx.number("QthreeGap", result["gap"])
    ctx.number("QthreeOptimal", PASS if result["optimal"] else FAIL)
    ctx.number("QthreeHorizon", horizon_t)
    ctx.number("QthreeFreeCells", result["free_cells"])
    ctx.number("QthreeCellsTotal", result["cells_total"])
    ctx.number("QthreeCandidates", result["candidates"])
    ctx.number("QthreeRows", result["rows"])
    ctx.number("QthreeGreedy", result["greedy"])
    ctx.number("QthreeCpsatStatus", result["cpsat"]["status"])
    ctx.number("QthreeCpsatSeconds", result["cpsat"]["seconds"], ".1f")
    ctx.number("QthreeCpsatValue", result["cpsat"]["value"])
    ctx.number("QthreeCpsatBound", result["bounds"]["cpsat"] if math.isfinite(result["bounds"]["cpsat"]) else "-")
    ctx.number("QthreeFreeCellBound", result["bounds"]["free_cells"])
    ctx.number("QthreePerBandBound", result["bounds"]["per_band"])
    ctx.number("QthreeEmptyRegionBound", empty_bound)
    if "lp" in result["bounds"]:
        ctx.number("QthreeLpBound", result["bounds"]["lp"])
        ctx.number("QthreeLpValue", result["lp"]["value"], ".2f")
    if result["highs_mip"]:
        ctx.number("QthreeHighsStatus", result["highs_mip"]["status"])
        ctx.number("QthreeHighsValue", int(result["highs_mip"].get("value", 0)))
        if "highs_mip" in result["bounds"]:
            ctx.number("QthreeHighsBound", result["bounds"]["highs_mip"])
    ctx.number("QthreeUtilBefore", 100 * result["utilisation_before"], ".1f")
    ctx.number("QthreeUtilAfter", 100 * result["utilisation_after"], ".1f")
    ctx.number("QthreeValidator", PASS)
    ctx.number("QthreeSpan", result["span"])
    if "original_horizon" in alternatives:
        ctx.number("QthreeAltHorizon", alt_horizon)
        ctx.number("QthreeAltNewPlans", alternatives["original_horizon"]["value"])
        ctx.number("QthreeAltUpperBound", alternatives["original_horizon"]["upper_bound"])
    return {
        "new_plans": result["value"],
        "upper_bound": result["upper_bound"],
        "gap": result["gap"],
        "status": result["cpsat"]["status"],
        "validator_ok": True,
    }


# --------------------------------------------------------------------------------------------- bench
@stage("bench", deps=("detect",), description="Exhaustive small-instance comparison and scaling benchmark")
def bench(ctx: StageContext) -> dict[str, Any]:
    workers = int(ctx.param("workers", 8))
    seed = ctx.seed_everything("bench")
    tiny_limits = Limits(fmax=2, tmax=1)
    tiny_bands = [int(b) for b in ctx.param("tiny_bands", [6, 7, 8, 9])]
    tiny_rows = []
    agree = 0
    deterministic = 0
    cancel_instances = 0
    for k in range(int(ctx.param("n_tiny", 24))):
        n_plans = 4 + k % 3
        # a crowded band budget forces cancellations, so the exhaustive comparison exercises the three
        # cancellation levels — the levels every optimality claim in the paper rests on (MDR-0007 addendum)
        plans = tiny_instance(seed + k, n_plans=n_plans, bands=tiny_bands[k % len(tiny_bands)])
        options = [enumerate_options(p, tiny_limits) for p in plans]
        model = build_cell_model(plans, options)
        t0 = time.perf_counter()
        truth = exhaustive_lexicographic(plans, tiny_limits, canonical_levels, model)
        t_exh = time.perf_counter() - t0
        res = solve_lexicographic_cpsat(model, canonical_levels(model), seed=seed, workers=workers, time_limit=120)
        again = solve_lexicographic_cpsat(model, canonical_levels(model), seed=seed, workers=workers, time_limit=120)
        same = res["vector"] == truth
        agree += int(same)
        deterministic += int(again["chosen"] == res["chosen"] and again["vector"] == res["vector"])
        cancels = sum(truth[0:3]) if truth and len(truth) == 7 else 0
        cancel_instances += int(cancels > 0)
        combos = 1
        for o in options:
            combos *= len(o)
        tiny_rows.append(
            {
                "instance": k + 1,
                "plans": n_plans,
                "bands": tiny_bands[k % len(tiny_bands)],
                "conflicts": len(detect_pairwise(plans)),
                "combinations": combos,
                "exhaustive_vector": truth,
                "cpsat_vector": res["vector"],
                "cancellations": cancels,
                "agree": same,
                "exhaustive_seconds": t_exh,
                "cpsat_seconds": res["seconds"],
            }
        )
    ctx.log.info("bench.tiny", agree=agree, total=len(tiny_rows), with_cancellations=cancel_instances)
    ctx.write_json("tiny.json", tiny_rows)

    scaling = []
    sizes = [int(v) for v in ctx.param("sizes", [150, 300, 600])]
    scale_limit = float(ctx.param("scale_time_limit", 120))
    repeats = int(ctx.param("timing_repeats", 3))

    def _median(xs: list[float]) -> float:
        ordered = sorted(xs)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])

    for n in sizes:
        plans = synthetic_instance(n, seed + n)
        # a single timing is noisy, so both detectors are timed `repeats` times and the median reported
        pair_times, sweep_times = [], []
        pairs = sweep = None
        for _ in range(repeats):
            t0 = time.perf_counter()
            pairs = detect_pairwise(plans)
            pair_times.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            sweep = detect_bandsweep(plans)
            sweep_times.append(time.perf_counter() - t0)
        options = [enumerate_options(p, Q2_LIMITS) for p in plans]
        t0 = time.perf_counter()
        model = build_cell_model(plans, options)
        t_build = time.perf_counter() - t0
        levels = canonical_levels(model)
        res = solve_weighted_cpsat(model, levels, seed=seed, workers=workers, time_limit=scale_limit)
        row = {
            "n": n,
            "horizon": horizon(plans),
            "conflicts": len(pairs or []),
            "detectors_agree": pairs == sweep,
            "repeats": repeats,
            "pairwise_seconds": _median(pair_times),
            "sweep_seconds": _median(sweep_times),
            "pairwise_seconds_max": max(pair_times),
            "sweep_seconds_max": max(sweep_times),
            "vars": model.n_vars,
            "rows": len(model.rows),
            "memberships": model.memberships,
            "build_seconds": t_build,
            "cpsat_status": res["status"],
            "cpsat_seconds": res["seconds"],
            "vector": res["vector"],
        }
        scaling.append(row)
        ctx.log.info("bench.scale", **row)
    ctx.write_json("scaling.json", scaling)
    ctx.number("BenchTinyInstances", len(tiny_rows))
    ctx.number("BenchTinyAgree", agree)
    ctx.number("BenchTinyAllAgree", PASS if agree == len(tiny_rows) else FAIL)
    ctx.number("BenchTinyDeterministic", deterministic)
    ctx.number("BenchTinyAllDeterministic", PASS if deterministic == len(tiny_rows) else FAIL)
    ctx.number("BenchTinyMaxCombinations", max(r["combinations"] for r in tiny_rows))
    ctx.number("BenchTinyWithCancellations", cancel_instances)
    ctx.number("BenchTinyMaxCancellations", max(r["cancellations"] for r in tiny_rows))
    ctx.number("BenchScaleMaxN", max(sizes))
    ctx.number("BenchScaleMinN", min(sizes))
    ctx.number("BenchScaleRepeats", repeats)
    # "Max" over every size, not the value at the largest size
    ctx.number("BenchScaleMaxPairwiseSeconds", max(r["pairwise_seconds"] for r in scaling), ".2f")
    ctx.number("BenchScaleMaxSweepSeconds", max(r["sweep_seconds"] for r in scaling), ".2f")
    ctx.number("BenchScaleMaxCpsatSeconds", max(r["cpsat_seconds"] for r in scaling), ".1f")
    ctx.number("BenchScaleLastPairwiseSeconds", scaling[-1]["pairwise_seconds"], ".2f")
    ctx.number("BenchScaleLastSweepSeconds", scaling[-1]["sweep_seconds"], ".2f")
    ctx.number("BenchScaleMaxStatus", scaling[-1]["cpsat_status"])
    ctx.number("BenchScaleAllOptimal", PASS if all(r["cpsat_status"] == "OPTIMAL" for r in scaling) else FAIL)
    ctx.number("BenchScaleDetectorsAgree", PASS if all(r["detectors_agree"] for r in scaling) else FAIL)
    return {
        "tiny_agree": agree,
        "tiny_deterministic": deterministic,
        "tiny_total": len(tiny_rows),
        "tiny_with_cancellations": cancel_instances,
        "scaling": [(r["n"], r["cpsat_status"], round(r["cpsat_seconds"], 1)) for r in scaling],
    }


# --------------------------------------------------------------------------------------- sensitivity
@stage(
    "sensitivity",
    deps=("detect", "resolve"),
    description="Q2 sensitivity to the maximum shift amplitudes (base case taken from `resolve`, others warm-started)",
)
def sensitivity(ctx: StageContext) -> dict[str, Any]:
    workers = int(ctx.param("workers", 8))
    seed = ctx.seed_everything("sensitivity")
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    base_report = ctx.dep_data("resolve", "solver_report.json")
    base_decisions = ctx.dep_data("resolve", "decisions.json")
    base_limits = (int(base_report["limits"]["fmax"]), int(base_report["limits"]["tmax"]))
    cases = ctx.param("cases", [[5, 2], [5, 5], [10, 2], [10, 5], [15, 5], [20, 10]])
    level_limits = ctx.param("level_time_limits", None) or float(ctx.param("time_limit", 60))
    rows = []
    for fmax, tmax in cases:
        limits = Limits(fmax=int(fmax), tmax=int(tmax))
        options = [enumerate_options(p, limits) for p in plans]
        model = build_cell_model(plans, options)
        if (limits.fmax, limits.tmax) == base_limits:
            # identical model: reuse the primary Q2 solution instead of re-solving with a shorter limit
            decisions = base_decisions
            vec = list(base_report["vector"])
            all_optimal, seconds, source = (
                bool(base_report["all_optimal"]),
                float(base_report["primary"]["seconds"]),
                "resolve",
            )
        else:
            hint = hint_from_decisions(model, base_decisions)
            res = solve_lexicographic_cpsat(
                model,
                canonical_levels(model),
                seed=seed,
                workers=workers,
                time_limit=level_limits,
                hint=hint,
                strength=strengthen(model),
            )
            decisions = decisions_from_choice(model, res["chosen"]) if res["chosen"] else []
            vec, all_optimal, seconds, source = res["vector"], res["all_optimal"], res["seconds"], "cp-sat"
        valid = (
            validators.validate_resolution(plans, decisions, fmax=limits.fmax, tmax=limits.tmax)
            if decisions
            else {"ok": False}
        )
        rows.append(
            {
                "fmax": int(fmax),
                "tmax": int(tmax),
                "vars": model.n_vars,
                "vector": vec,
                "cancel_total": sum(vec[0:3]) if len(vec) == 7 else None,
                "adjust_total": sum(vec[3:6]) if len(vec) == 7 else None,
                "amplitude": vec[6] / 10.0 if len(vec) == 7 else None,
                "table": table_from_decisions(decisions) if decisions else None,
                "all_optimal": all_optimal,
                "seconds": seconds,
                "source": source,
                "validator_ok": bool(valid["ok"]),
                "shifts": _shift_stats(decisions),
            }
        )
        ctx.log.info("sensitivity.case", fmax=fmax, tmax=tmax, vector=vec, seconds=seconds, source=source)
    ctx.write_json("cases.json", rows)
    base = next((r for r in rows if (r["fmax"], r["tmax"]) == base_limits), rows[0])
    # lexicographic monotonicity: a larger action set can never give a worse vector than the base solution
    monotone = all(
        list(r["vector"]) <= list(base["vector"])
        for r in rows
        if len(r["vector"]) == 7 and r["fmax"] >= base_limits[0] and r["tmax"] >= base_limits[1]
    ) and all(
        list(r["vector"]) >= list(base["vector"])
        for r in rows
        if len(r["vector"]) == 7 and r["fmax"] <= base_limits[0] and r["tmax"] <= base_limits[1]
    )
    ctx.number("SensCases", len(rows))
    ctx.number("SensBaseAdjustTotal", base["adjust_total"])
    ctx.number("SensBaseCancelTotal", base["cancel_total"])
    ctx.number("SensMinAdjustTotal", min(r["adjust_total"] for r in rows if r["adjust_total"] is not None))
    ctx.number("SensMaxAdjustTotal", max(r["adjust_total"] for r in rows if r["adjust_total"] is not None))
    ctx.number("SensMaxCancelTotal", max(r["cancel_total"] for r in rows if r["cancel_total"] is not None))
    ctx.number("SensMinCancelTotal", min(r["cancel_total"] for r in rows if r["cancel_total"] is not None))
    ctx.number("SensAllOptimal", PASS if all(r["all_optimal"] for r in rows) else FAIL)
    ctx.number("SensAllValid", PASS if all(r["validator_ok"] for r in rows) else FAIL)
    ctx.number("SensMonotone", PASS if monotone else FAIL)
    # Per-case macros, so that the paper can attribute a change to one parameter at a time instead of
    # quoting the extremum over the whole grid (which varies both limits at once).
    words = {
        2: "Two",
        3: "Three",
        4: "Four",
        5: "Five",
        6: "Six",
        9: "Nine",
        10: "Ten",
        11: "Eleven",
        15: "Fifteen",
        20: "Twenty",
    }
    by_case = {(r["fmax"], r["tmax"]): r for r in rows}
    for (fmax, tmax), r in by_case.items():
        if fmax in words and tmax in words and r["cancel_total"] is not None:
            key = f"SensPhi{words[fmax]}Tau{words[tmax]}"
            ctx.number(f"{key}Cancel", r["cancel_total"])
            ctx.number(f"{key}Adjust", r["adjust_total"])

    # One-at-a-time elasticities: cancellations avoided per extra unit of each limit, holding the other
    # at the value the problem statement gives. Reported instead of the raw "twice as effective" claim,
    # which compares a +5 df increment against a +3 dt increment.
    def _cancel(fmax: int, tmax: int) -> int | None:
        r = by_case.get((fmax, tmax))
        return None if r is None else r["cancel_total"]

    base_f, base_t = int(base["fmax"]), int(base["tmax"])
    lo_f, lo_t = _cancel(5, base_t), _cancel(base_f, 2)
    if lo_f is not None and base["cancel_total"] is not None:
        ctx.number("SensFreqElasticity", (lo_f - base["cancel_total"]) / (base_f - 5), ".1f")
        ctx.number("SensFreqLowCancel", lo_f)
    if lo_t is not None and base["cancel_total"] is not None:
        ctx.number("SensTimeElasticity", (lo_t - base["cancel_total"]) / (base_t - 2), ".1f")
        ctx.number("SensTimeLowCancel", lo_t)
    if lo_f is not None and lo_t is not None and base["cancel_total"] is not None:
        per_f = (lo_f - base["cancel_total"]) / (base_f - 5)
        per_t = (lo_t - base["cancel_total"]) / (base_t - 2)
        ctx.number("SensElasticityRatio", per_f / per_t if per_t else float("nan"), ".2f")
    return {"cases": [(r["fmax"], r["tmax"], r["vector"]) for r in rows], "monotone": monotone}


# ------------------------------------------------------------------------------------------- results
@stage(
    "results",
    deps=("detect", "resolve", "pack", "resolve_interval"),
    description="Fill result1–4.xlsx from the organisers' templates after every validator passed",
)
def results(ctx: StageContext) -> dict[str, Any]:
    for name in ("detect", "resolve", "pack", "resolve_interval"):
        report = ctx.dep_data(name, "validation_report.json")
        if not report.get("ok"):
            raise RuntimeError(f"validator of stage {name} did not pass; refusing to write result workbooks")
    templates = ctx.templates
    written: dict[str, Any] = {}

    conflicts = ctx.dep_data("detect", "conflicts.json")
    rows1 = [
        [k, r["id1"], r["id2"]] for k, r in enumerate(sorted(conflicts, key=lambda r: (r["id1"], r["id2"])), start=1)
    ]
    written["result1.xlsx"] = write_result(
        templates / "result1.xlsx", ctx.out("result1.xlsx"), {"Sheet1": (["序号", "冲突装备1", "冲突设备2"], rows1)}
    )

    def adjustment_rows(decisions: list[dict[str, Any]], with_gap: bool) -> list[list[Any]]:
        rows: list[list[Any]] = []
        for dec in sorted(decisions, key=lambda d: d["pid"]):
            if dec["kind"] == "keep":
                continue
            plan = plan_from_record(dec["plan"]) if dec["plan"] else None
            freq = plan.freq_text() if plan and dec["kind"] == "freq" else None
            tim = plan.time_text() if plan and dec["kind"] == "time" else None
            gap = plan.g if plan and dec["kind"] == "gap" else None
            cancel = "是" if dec["kind"] == "cancel" else None
            rows.append([dec["pid"], freq, tim, gap, cancel] if with_gap else [dec["pid"], freq, tim, cancel])
        return rows

    rows2 = adjustment_rows(ctx.dep_data("resolve", "decisions.json"), with_gap=False)
    written["result2.xlsx"] = write_result(
        templates / "result2.xlsx",
        ctx.out("result2.xlsx"),
        {"Sheet1": (["用频装备编号", "调整后频段区间", "调整后时间区间", "是否撤销用频计划"], rows2)},
    )
    new_plans = _plans(ctx.dep_data("pack", "new_plans.json"))
    rows3 = [[k, p.freq_text(), p.time_text()] for k, p in enumerate(new_plans, start=1)]
    written["result3.xlsx"] = write_result(
        templates / "result3.xlsx",
        ctx.out("result3.xlsx"),
        {"Sheet1": (["新增用频装备序号", "调整后频段区间", "调整后时间区间"], rows3)},
    )
    rows4 = adjustment_rows(ctx.dep_data("resolve_interval", "decisions.json"), with_gap=True)
    written["result4.xlsx"] = write_result(
        templates / "result4.xlsx",
        ctx.out("result4.xlsx"),
        {"Sheet1": (["用频装备编号", "调整后频段范围", "调整后时间区间", "调整后间隔时长", "是否撤销用频计划"], rows4)},
    )
    ctx.write_json("results_report.json", written)
    ctx.number("ResultOneRows", len(rows1))
    ctx.number("ResultTwoRows", len(rows2))
    ctx.number("ResultThreeRows", len(rows3))
    ctx.number("ResultFourRows", len(rows4))
    return {name: info["sheets"]["Sheet1"]["rows"] for name, info in written.items()}


from pipelines.d import report as _report  # noqa: E402,F401  (registers figures/tables stages)
