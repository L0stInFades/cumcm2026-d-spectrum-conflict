"""Problem D: packing model on analytically solvable regions."""

from __future__ import annotations

import numpy as np

from pipelines.d.pack import (
    C_TEMPLATE,
    candidate_placements,
    cell_rows,
    greedy_pack,
    highs_pack,
    occupancy_grid,
    plans_from_choice,
    solve_pack_cpsat,
    template_span,
)
from pipelines.d.plans import Plan
from pipelines.d.validators import validate_packing


def test_empty_strip_packs_five_phases() -> None:
    # 3 free bands over exactly one span: five plans with starts 0,2,4,6,8 tile the strip (period 10, duration 2)
    horizon = template_span(C_TEMPLATE)  # 112
    grid = np.ones((100, horizon), dtype=bool)
    grid[0:3, :] = False
    cands = candidate_placements(grid, C_TEMPLATE)
    assert cands.tolist() == [[0, 0]]  # only s = 0 fits inside the horizon
    grid = np.ones((100, horizon + 8), dtype=bool)
    grid[0:3, :] = False
    cands = candidate_placements(grid, C_TEMPLATE)
    assert len(cands) == 9
    rows = cell_rows(cands, C_TEMPLATE, horizon + 8)
    res = solve_pack_cpsat(rows, len(cands), hint=None, seed=0, workers=1, time_limit=30)
    assert res["status"] == "OPTIMAL" and res["value"] == 5
    lp = highs_pack(rows, len(cands), integer=False, time_limit=30, seed=0, threads=1)
    assert lp["value"] >= 5 - 1e-6
    new_plans = plans_from_choice(cands, res["chosen"], C_TEMPLATE)
    report = validate_packing([], new_plans, horizon=horizon + 8, template=C_TEMPLATE)
    assert report["ok"], report["errors"]


def test_existing_plan_blocks_candidates_and_greedy_is_feasible() -> None:
    existing = [Plan("C001", "C", 0, 3, 0, 2, 8, 12)]
    horizon = 130
    grid = occupancy_grid(existing, horizon)
    assert grid.sum() == 72
    cands = candidate_placements(grid, C_TEMPLATE)
    assert not any((f < 3 and s % 10 in (0, 1, 9)) for f, s in cands.tolist() if s <= 110)
    greedy = greedy_pack(cands, C_TEMPLATE, grid)
    new_plans = plans_from_choice(cands, greedy, C_TEMPLATE)
    report = validate_packing(existing, new_plans, horizon=horizon, template=C_TEMPLATE)
    assert report["ok"] and len(new_plans) == len(greedy) > 0
