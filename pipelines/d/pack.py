"""Problem 3: pack as many additional C-class plans as possible into the free time–frequency cells left by
the Problem-2 solution (MDR-0005). Variables x[f,s] (band start, first-use start); AtMostOne per cell.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import numpy as np

from pipelines.d.highs_util import highs_threads
from pipelines.d.plans import BANDS, Plan

C_TEMPLATE = {"w": 3, "d": 2, "g": 8, "n": 12}


def template_span(template: dict[str, int]) -> int:
    return template["d"] + (template["n"] - 1) * (template["d"] + template["g"])


def template_offsets(template: dict[str, int]) -> np.ndarray:
    """Time offsets (relative to the first-use start) occupied by one plan of the template."""
    period = template["d"] + template["g"]
    return np.array([k * period + j for k in range(template["n"]) for j in range(template["d"])], dtype=np.int64)


def occupancy_grid(plans: list[Plan], horizon: int, bands: int = BANDS) -> np.ndarray:
    """Boolean (bands × horizon) grid of occupied cells."""
    grid = np.zeros((bands, horizon), dtype=bool)
    for p in plans:
        for start, end in p.uses():
            grid[p.f : p.f_end, start:end] = True
    return grid


def candidate_placements(grid: np.ndarray, template: dict[str, int]) -> np.ndarray:
    """All (f, s) whose template cells are free and end within the horizon; shape (m, 2)."""
    bands, horizon = grid.shape
    span = template_span(template)
    offsets = template_offsets(template)
    free = ~grid
    width = template["w"]
    n_s = horizon - span + 1
    if n_s <= 0:
        return np.zeros((0, 2), dtype=np.int64)
    rows = []
    for f in range(bands - width + 1):
        strip = np.all(free[f : f + width], axis=0)  # time slots free on all bands of the strip
        windows = strip[np.arange(n_s)[:, None] + offsets[None, :]]  # (n_s, cells per plan)
        ok = np.all(windows, axis=1)
        for s in np.flatnonzero(ok):
            rows.append((f, int(s)))
    return np.array(rows, dtype=np.int64).reshape(-1, 2)


def cell_rows(candidates: np.ndarray, template: dict[str, int], horizon: int) -> list[list[int]]:
    """Deduplicated cell rows (lists of candidate indices) with at least two candidates."""
    offsets = template_offsets(template)
    cells: dict[int, list[int]] = {}
    for v, (f, s) in enumerate(candidates.tolist()):
        for band in range(f, f + template["w"]):
            base = band * horizon + s
            for off in offsets.tolist():
                cells.setdefault(base + off, []).append(v)
    rows = {tuple(r) for r in cells.values() if len(r) >= 2}
    return [list(r) for r in sorted(rows)]


def greedy_pack(candidates: np.ndarray, template: dict[str, int], grid: np.ndarray) -> list[int]:
    """First-fit greedy (by start time, then band): a feasible lower bound and a CP-SAT hint."""
    occ = grid.copy()
    offsets = template_offsets(template)
    order = np.lexsort((candidates[:, 0], candidates[:, 1]))
    chosen = []
    for v in order.tolist():
        f, s = candidates[v]
        block = occ[f : f + template["w"]][:, s + offsets]
        if not block.any():
            occ[f : f + template["w"], s + offsets] = True
            chosen.append(v)
    return chosen


def solve_pack_cpsat(
    rows: list[list[int]],
    n_candidates: int,
    *,
    hint: list[int] | None,
    seed: int,
    workers: int = 8,
    time_limit: float = 900.0,
) -> dict[str, Any]:
    from ortools.sat.python import cp_model

    t0 = time.monotonic()
    cp = cp_model.CpModel()
    x = [cp.NewBoolVar(f"x{v}") for v in range(n_candidates)]
    for row in rows:
        cp.AddAtMostOne(x[v] for v in row)
    cp.Maximize(sum(x))
    if hint:
        hinted = set(hint)
        for v in range(n_candidates):
            cp.AddHint(x[v], v in hinted)
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_workers = int(workers)
    solver.parameters.max_time_in_seconds = float(time_limit)
    status = solver.Solve(cp)
    chosen = (
        [v for v in range(n_candidates) if solver.Value(x[v])]
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        else []
    )
    return {
        "solver": "cp-sat",
        "status": solver.StatusName(status),
        "value": len(chosen),
        "bound": float(solver.BestObjectiveBound()) if chosen else None,
        "chosen": chosen,
        "seconds": round(time.monotonic() - t0, 3),
        "n_vars": n_candidates,
        "n_rows": len(rows),
    }


def highs_pack(
    rows: list[list[int]], n_candidates: int, *, integer: bool, time_limit: float, seed: int, threads: int = 8
) -> dict[str, Any]:
    """LP relaxation upper bound (integer=False) or a MILP cross-check with its dual bound (integer=True)."""
    import highspy

    t0 = time.monotonic()
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("random_seed", int(seed))
    h.setOptionValue("threads", highs_threads(threads))
    h.setOptionValue("mip_rel_gap", 0.0)
    h.setOptionValue("mip_abs_gap", 0.0)
    n = n_candidates
    h.addVars(n, np.zeros(n), np.ones(n))
    if integer:
        h.changeColsIntegrality(n, np.arange(n, dtype=np.int32), np.array([highspy.HighsVarType.kInteger] * n))
    starts, index = [], []
    nnz = 0
    for row in rows:
        starts.append(nnz)
        index.extend(row)
        nnz += len(row)
    h.addRows(
        len(rows),
        np.full(len(rows), -highspy.kHighsInf),
        np.ones(len(rows)),
        nnz,
        np.array(starts, dtype=np.int32),
        np.array(index, dtype=np.int32),
        np.ones(nnz),
    )
    h.changeColsCost(n, np.arange(n, dtype=np.int32), -np.ones(n))  # maximise sum x
    h.run()
    status = h.modelStatusToString(h.getModelStatus())
    info = h.getInfo()
    out: dict[str, Any] = {"status": status, "seconds": round(time.monotonic() - t0, 3), "integer": integer}
    if integer:
        out["value"] = -float(info.objective_function_value)
        out["bound"] = -float(info.mip_dual_bound)
        sol = np.array(h.getSolution().col_value)
        out["chosen"] = [int(v) for v in np.flatnonzero(sol > 0.5)]
    else:
        out["value"] = -float(info.objective_function_value)
    return out


def plan_offsets(plan: Plan) -> np.ndarray:
    """Time offsets (relative to the first-use start) occupied by ``plan``."""
    return np.array([k * plan.period + j for k in range(plan.n) for j in range(plan.d)], dtype=np.int64)


def free_positions(grid: np.ndarray, width: int, offsets: np.ndarray, *, first_only: bool = False) -> np.ndarray:
    """All (f, s) at which a plan of this shape fits in the free cells of ``grid``; shape (m, 2).

    With ``first_only`` the scan stops at the lexicographically smallest (f, s), which is what first-fit
    needs and keeps the repack linear in the number of plans rather than in the number of positions."""
    bands, horizon = grid.shape
    span = int(offsets[-1]) + 1
    n_s = horizon - span + 1
    if n_s <= 0 or width > bands:
        return np.zeros((0, 2), dtype=np.int64)
    free = ~grid
    rows = []
    windows_index = np.arange(n_s)[:, None] + offsets[None, :]
    for f in range(bands - width + 1):
        strip = np.all(free[f : f + width], axis=0)
        ok = np.flatnonzero(np.all(strip[windows_index], axis=1))
        if first_only:
            if len(ok):
                return np.array([(f, int(ok[0]))], dtype=np.int64)
            continue
        rows.extend((f, int(s)) for s in ok)
    return np.array(rows, dtype=np.int64).reshape(-1, 2)


def repack_existing(plans: list[Plan], horizon: int, bands: int = BANDS) -> tuple[list[Plan], np.ndarray]:
    """First-fit decreasing re-placement of every plan (MDR-0010, interpretation B).

    Each plan keeps ``w``, ``d``, ``g`` and ``n`` — only its band start and first-use start move, by an
    unrestricted amount — so the number of cells it occupies is unchanged. Plans are placed largest-first
    at the lexicographically smallest free (f, s), which compacts them towards low bands and early times
    and leaves a large contiguous free region. Raises when a plan cannot be placed at all."""
    grid = np.zeros((bands, horizon), dtype=bool)
    order = sorted(plans, key=lambda p: (-(p.w * p.d * p.n), -p.w, p.pid))
    placed: list[Plan] = []
    for plan in order:
        offsets = plan_offsets(plan)
        spots = free_positions(grid, plan.w, offsets, first_only=True)
        if not len(spots):
            raise RuntimeError(f"first-fit decreasing could not place {plan.pid} within {bands}x{horizon}")
        f, s = (int(v) for v in spots[0])
        grid[f : f + plan.w, s + offsets] = True
        placed.append(replace(plan, f=f, s=s))
    return sorted(placed, key=lambda p: p.pid), grid


def plans_from_choice(candidates: np.ndarray, chosen: list[int], template: dict[str, int]) -> list[Plan]:
    """New C plans (ids N001, N002, …) in (start, band) order."""
    picked = sorted((int(candidates[v, 1]), int(candidates[v, 0])) for v in chosen)
    return [
        Plan(f"N{k:03d}", "C", f, template["w"], s, template["d"], template["g"], template["n"])
        for k, (s, f) in enumerate(picked, start=1)
    ]
