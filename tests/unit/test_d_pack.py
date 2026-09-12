"""Problem D: packing model on analytically solvable regions."""

from __future__ import annotations

import numpy as np
import pytest

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
from pipelines.d.plans import Plan
from pipelines.d.validators import conflicts_by_cells, validate_packing


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


def test_repack_keeps_parameters_compacts_and_stays_conflict_free() -> None:
    """MDR-0010 interpretation B: first-fit decreasing may move a plan anywhere but must not change it."""
    scattered = [
        Plan("A001", "A", 80, 10, 30, 5, 60, 3),
        Plan("B001", "B", 40, 15, 7, 3, 40, 4),
        Plan("B002", "B", 60, 15, 90, 3, 40, 4),
        Plan("C001", "C", 20, 3, 11, 2, 8, 12),
        Plan("C002", "C", 97, 3, 40, 2, 8, 12),
    ]
    horizon = 300
    repacked, grid = repack_existing(scattered, horizon)
    assert [p.pid for p in repacked] == sorted(p.pid for p in scattered)
    before = {p.pid: p for p in scattered}
    for p in repacked:
        q = before[p.pid]
        assert (p.w, p.d, p.g, p.n, p.cat) == (q.w, q.d, q.g, q.n, q.cat)  # only f and s may move
        assert 0 <= p.f and p.f_end <= 100 and p.s >= 0 and p.end <= horizon
    assert not conflicts_by_cells(repacked)  # the layout itself is conflict-free
    assert grid.sum() == sum(p.n_cells for p in scattered)  # no cell is double-counted
    assert max(p.f_end for p in repacked) <= max(p.f_end for p in scattered)  # compacted towards low bands
    # the repacked layout admits at least as many new C plans as the scattered one
    scattered_grid = occupancy_grid(scattered, horizon)
    assert len(candidate_placements(grid, C_TEMPLATE)) >= len(candidate_placements(scattered_grid, C_TEMPLATE))


def test_repack_fills_a_strip_exactly_and_refuses_an_impossible_region() -> None:
    # period 10, duration 2: five phases (s = 0,2,4,6,8) tile a 3-band strip, but only once every offset
    # still ends inside the horizon, i.e. from span + 8 = 120 onwards
    horizon = template_span(C_TEMPLATE) + 8
    strip = [Plan(f"C{k:03d}", "C", 0, 3, 2 * k, 2, 8, 12) for k in range(5)]
    repacked, grid = repack_existing(strip, horizon)
    assert not conflicts_by_cells(repacked)
    assert sorted(p.s for p in repacked) == [0, 2, 4, 6, 8]  # first-fit reproduces the five phases
    assert grid[0:3].all() and not grid[3:].any()  # and they tile exactly the first three bands
    with pytest.raises(RuntimeError, match="could not place"):
        repack_existing([*strip, Plan("C999", "C", 0, 3, 0, 2, 8, 12)], horizon, bands=3)
