"""Synthetic instances and an exhaustive reference solver for benchmarking (MDR-0007)."""

from __future__ import annotations

import random
from itertools import combinations
from typing import Any

from pipelines.d.detect import plans_conflict
from pipelines.d.plans import BANDS, Plan
from pipelines.d.resolve import CellModel, Level, Limits, Option, enumerate_options

CATEGORY_PARAMS = {"A": (10, 5, 60, 3), "B": (15, 3, 40, 4), "C": (3, 2, 8, 12)}  # (w, d, g, n)
CATEGORY_SHARE = {"A": 20, "B": 40, "C": 90}


def synthetic_instance(n: int, seed: int, *, base_n: int = 150, base_start_max: int = 531) -> list[Plan]:
    """``n`` plans with the attachment's category mix and parameters; the time range scales with ``n``
    so that the occupancy density stays comparable to the real instance."""
    rng = random.Random(seed)
    start_max = max(1, round(base_start_max * n / base_n))
    plans: list[Plan] = []
    counts = {c: round(n * share / base_n) for c, share in CATEGORY_SHARE.items()}
    counts["C"] += n - sum(counts.values())
    for cat, count in counts.items():
        w, d, g, m = CATEGORY_PARAMS[cat]
        for k in range(count):
            plans.append(
                Plan(f"{cat}{k + 1:03d}", cat, rng.randint(0, BANDS - w), w, rng.randint(0, start_max), d, g, m)
            )
    return plans


def tiny_instance(seed: int, *, n_plans: int = 5, bands: int = 12) -> list[Plan]:
    """A crowded miniature instance for exhaustive comparison."""
    rng = random.Random(seed)
    plans = []
    for k in range(n_plans):
        cat = rng.choice("ABC")
        w = rng.randint(2, 3)
        plans.append(
            Plan(
                f"{cat}{k + 1:03d}",
                cat,
                rng.randint(0, bands - w),
                w,
                rng.randint(0, 6),
                rng.randint(1, 2),
                rng.randint(1, 3),
                rng.randint(2, 3),
            )
        )
    return plans


def exhaustive_lexicographic(plans: list[Plan], limits: Limits, levels_fn: Any, model: CellModel) -> list[int] | None:
    """Depth-first enumeration of every action combination; returns the lexicographically smallest level vector.

    ``levels_fn(model)`` gives the levels; conflicts are decided with ``plans_conflict`` on the applied plans,
    i.e. by interval arithmetic rather than by the cell rows, so the comparison with CP-SAT is meaningful."""
    levels: list[Level] = levels_fn(model)
    n = len(plans)
    applied: list[list[Plan | None]] = [[opt.apply(p) for opt in model.options[i]] for i, p in enumerate(plans)]
    conflict: dict[tuple[int, int, int, int], bool] = {}
    for i, j in combinations(range(n), 2):
        for oi, pi in enumerate(applied[i]):
            for oj, pj in enumerate(applied[j]):
                conflict[(i, oi, j, oj)] = pi is not None and pj is not None and plans_conflict(pi, pj)
    best: list[int] | None = None
    choice: list[int] = []

    def rec(i: int) -> None:
        nonlocal best
        if i == n:
            vec = [sum(terms.get(model.plan_vars[k][choice[k]], 0) for k in range(n)) for _, terms in levels]
            if best is None or vec < best:
                best = vec
            return
        for o in range(len(model.options[i])):
            if all(not conflict[(k, choice[k], i, o)] for k in range(i)):
                choice.append(o)
                rec(i + 1)
                choice.pop()

    rec(0)
    return best


def options_for(plans: list[Plan], limits: Limits) -> list[list[Option]]:
    return [enumerate_options(p, limits) for p in plans]
