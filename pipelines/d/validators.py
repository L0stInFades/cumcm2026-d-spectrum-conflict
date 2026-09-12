"""Independent validators for Problem D (deliberately separate from detect.py / resolve.py / pack.py).

Every check here re-derives what a plan occupies from first principles — the plan is expanded into an
explicit set of (band, time) cells and conflicts are found by set intersection — so that agreement with
the interval-arithmetic detectors and the CP-SAT/HiGHS solutions is genuine, not tautological.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from pipelines.d.plans import BANDS, CATEGORIES, Plan

KINDS = ("keep", "freq", "time", "gap", "cancel")


def cell_set(plan: Plan) -> set[tuple[int, int]]:
    """Every (band, time) cell the plan occupies, from the definition of its uses."""
    cells: set[tuple[int, int]] = set()
    for k in range(plan.n):
        start = plan.s + k * (plan.d + plan.g)
        for band in range(plan.f, plan.f + plan.w):
            for t in range(start, start + plan.d):
                cells.add((band, t))
    return cells


def conflicts_by_cells(plans: list[Plan]) -> list[tuple[str, str]]:
    """All conflicting id pairs (id1 < id2), found by intersecting cell sets."""
    cells = {p.pid: cell_set(p) for p in plans}
    out = []
    for a, b in combinations(plans, 2):
        if cells[a.pid] & cells[b.pid]:
            out.append((min(a.pid, b.pid), max(a.pid, b.pid)))
    return sorted(out)


def plan_bounds_errors(plan: Plan) -> list[str]:
    errors = []
    if plan.f < 0 or plan.f + plan.w > BANDS:
        errors.append(f"{plan.pid}: bands {plan.f}..{plan.f + plan.w} outside [0,{BANDS})")
    if plan.s < 0:
        errors.append(f"{plan.pid}: start {plan.s} < 0")
    if plan.g < 1 or plan.n < 1 or plan.d < 1 or plan.w < 1:
        errors.append(f"{plan.pid}: non-positive parameter (w={plan.w}, d={plan.d}, g={plan.g}, n={plan.n})")
    return errors


def validate_detection(plans: list[Plan], reported: list[tuple[str, str]]) -> dict[str, Any]:
    """Compare a reported conflict list with the cell-set ground truth."""
    truth = conflicts_by_cells(plans)
    rep = sorted((min(a, b), max(a, b)) for a, b in reported)
    missing = sorted(set(truth) - set(rep))
    extra = sorted(set(rep) - set(truth))
    duplicates = len(rep) - len(set(rep))
    ok = not missing and not extra and duplicates == 0
    return {
        "ok": ok,
        "method": "cell-set intersection",
        "truth_pairs": len(truth),
        "reported_pairs": len(rep),
        "missing": missing[:20],
        "extra": extra[:20],
        "duplicates": duplicates,
    }


def _changed_fields(before: Plan, after: Plan) -> list[str]:
    return [name for name in ("f", "w", "s", "d", "g", "n") if getattr(before, name) != getattr(after, name)]


def validate_resolution(
    original: list[Plan],
    decisions: list[dict[str, Any]],
    *,
    fmax: int,
    tmax: int,
    gmax: int = 0,
    gap_categories: tuple[str, ...] = (),
    horizon_cap: int = 0,
    reported_table: dict[str, dict[str, int]] | None = None,
    reported_vector: list[int] | None = None,
) -> dict[str, Any]:
    """Check a resolution: one legal action per plan, one changed parameter, amplitude limits, bounds,
    zero conflicts among surviving plans, and (optionally) the reported Table-1 statistics / objective."""
    errors: list[str] = []
    by_id = {p.pid: p for p in original}
    seen: set[str] = set()
    survivors: list[Plan] = []
    table = {c: {"keep": 0, "adjust": 0, "cancel": 0} for c in CATEGORIES}
    vector = {"cancel": dict.fromkeys(CATEGORIES, 0), "adjust": dict.fromkeys(CATEGORIES, 0), "amplitude": 0}
    for dec in decisions:
        pid = str(dec["pid"])
        kind = str(dec["kind"])
        if pid not in by_id:
            errors.append(f"unknown plan {pid}")
            continue
        if pid in seen:
            errors.append(f"{pid}: more than one decision")
            continue
        seen.add(pid)
        before = by_id[pid]
        if kind not in KINDS:
            errors.append(f"{pid}: unknown action {kind!r}")
            continue
        if kind == "cancel":
            table[before.cat]["cancel"] += 1
            vector["cancel"][before.cat] += 1
            continue
        after = Plan(**dec["plan"]) if dec.get("plan") else before
        if after.pid != pid or after.cat != before.cat:
            errors.append(f"{pid}: identity changed in adjusted plan")
        changed = _changed_fields(before, after)
        expected = {"keep": [], "freq": ["f"], "time": ["s"], "gap": ["g"]}[kind]
        if changed != expected:
            errors.append(f"{pid}: action {kind} but changed fields {changed}")
        errors += plan_bounds_errors(after)
        if kind == "freq" and abs(after.f - before.f) > fmax:
            errors.append(f"{pid}: band shift {after.f - before.f} exceeds {fmax}")
        if kind == "time" and abs(after.s - before.s) > tmax:
            errors.append(f"{pid}: time shift {after.s - before.s} exceeds {tmax}")
        if kind == "gap":
            if before.cat not in gap_categories:
                errors.append(f"{pid}: gap change not allowed for category {before.cat}")
            if abs(after.g - before.g) > gmax:
                errors.append(f"{pid}: gap change {after.g - before.g} exceeds {gmax}")
        survivors.append(after)
        if kind == "keep":
            table[before.cat]["keep"] += 1
        else:
            table[before.cat]["adjust"] += 1
            vector["adjust"][before.cat] += 1
            vector["amplitude"] += {
                "freq": abs(after.f - before.f),
                "time": 2 * abs(after.s - before.s),
                "gap": abs(after.g - before.g),
            }[kind]
    undecided = sorted(set(by_id) - seen)
    if undecided:
        errors.append(f"{len(undecided)} plans without decision, e.g. {undecided[:5]}")
    if horizon_cap:
        late = [p.pid for p in survivors if p.end > horizon_cap]
        if late:
            errors.append(f"{len(late)} surviving plans end after the horizon cap {horizon_cap}, e.g. {late[:5]}")
    remaining = conflicts_by_cells(survivors)
    if remaining:
        errors.append(f"{len(remaining)} conflicts remain, e.g. {remaining[:5]}")
    if reported_table is not None and reported_table != table:
        errors.append(f"reported table {reported_table} differs from recomputed {table}")
    recomputed_vector = [vector["cancel"][c] for c in CATEGORIES] + [vector["adjust"][c] for c in CATEGORIES]
    recomputed_vector.append(int(vector["amplitude"]))
    if reported_vector is not None and list(reported_vector) != recomputed_vector:
        errors.append(f"reported objective {reported_vector} differs from recomputed {recomputed_vector}")
    return {
        "ok": not errors,
        "method": "independent per-plan legality checks + cell-set conflict scan",
        "errors": errors[:30],
        "n_decisions": len(decisions),
        "n_survivors": len(survivors),
        "remaining_conflicts": len(remaining),
        "table": table,
        "vector": recomputed_vector,
        "amplitude_normalised": vector["amplitude"] / 10.0,
        "horizon": max((p.end for p in survivors), default=0),
    }


def validate_packing(
    existing: list[Plan], new_plans: list[Plan], *, horizon: int, template: dict[str, int]
) -> dict[str, Any]:
    """Check new plans: template parameters, bounds, inside the horizon, no conflicts with anything."""
    errors: list[str] = []
    for p in new_plans:
        if (p.w, p.d, p.g, p.n) != (template["w"], template["d"], template["g"], template["n"]):
            errors.append(f"{p.pid}: parameters {(p.w, p.d, p.g, p.n)} differ from template")
        if p.cat != "C":
            errors.append(f"{p.pid}: category {p.cat} is not C")
        errors += plan_bounds_errors(p)
        if p.end > horizon:
            errors.append(f"{p.pid}: ends at {p.end} > horizon {horizon}")
    ids = [p.pid for p in new_plans]
    if len(ids) != len(set(ids)) or set(ids) & {p.pid for p in existing}:
        errors.append("duplicate or clashing plan ids")
    remaining = conflicts_by_cells(existing + new_plans)
    if remaining:
        errors.append(f"{len(remaining)} conflicts, e.g. {remaining[:5]}")
    return {
        "ok": not errors,
        "method": "parameter/bound checks + cell-set conflict scan over existing and new plans",
        "errors": errors[:30],
        "n_new": len(new_plans),
        "remaining_conflicts": len(remaining),
        "cells_new": sum(p.n_cells for p in new_plans),
    }
