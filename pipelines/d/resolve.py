"""Conflict resolution (Problems 2 and 4): actions, time–frequency cell model, lexicographic CP-SAT,
separated-weight cross-checks and HiGHS MILP / LP bounds (MDR-0002, MDR-0003, MDR-0004).

Model. Plan ``i`` chooses exactly one action ``o`` (Boolean ``y[i,o]``). Two (plan, action) pairs
conflict iff they share a (band, time) cell, so ``AtMostOne`` over the variables covering each cell is an
exact encoding of "no conflict remains". Objectives are lists of levels; each level is a linear form in
the ``y`` variables and is minimised after fixing the optimal values of the previous levels.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pipelines.d.plans import BANDS, CATEGORIES, Plan

# amplitude normalisation (MDR-0003): |δ|/10 + |τ|/5 + |Δg|/10, stored ×10 so that it is an integer
AMPLITUDE_SCALE = 10
FREQ_REF, TIME_REF, GAP_REF = 10, 5, 10


@dataclass(frozen=True)
class Option:
    """One action for a plan: keep, band shift, time shift, gap change or cancel."""

    kind: str
    delta: int = 0

    def apply(self, plan: Plan) -> Plan | None:
        if self.kind == "cancel":
            return None
        if self.kind == "keep":
            return plan
        if self.kind == "freq":
            return plan.shifted(df=self.delta)
        if self.kind == "time":
            return plan.shifted(dt=self.delta)
        if self.kind == "gap":
            return plan.shifted(gap=plan.g + self.delta)
        raise ValueError(f"unknown action {self.kind!r}")

    @property
    def amplitude(self) -> int:
        """Scaled amplitude (×10 of the normalised amplitude)."""
        if self.kind == "freq":
            return abs(self.delta) * AMPLITUDE_SCALE // FREQ_REF
        if self.kind == "time":
            return abs(self.delta) * AMPLITUDE_SCALE // TIME_REF
        if self.kind == "gap":
            return abs(self.delta) * AMPLITUDE_SCALE // GAP_REF
        return 0

    @property
    def is_adjust(self) -> bool:
        return self.kind in {"freq", "time", "gap"}

    def label(self) -> str:
        return self.kind if self.kind in {"keep", "cancel"} else f"{self.kind}{self.delta:+d}"


@dataclass(frozen=True)
class Limits:
    fmax: int = 10
    tmax: int = 5
    gmax: int = 0
    gap_categories: tuple[str, ...] = ()
    allow_cancel: bool = True


def enumerate_options(plan: Plan, limits: Limits) -> list[Option]:
    """All legal actions of a plan under the limits (band interval inside [0,100), start >= 0, gap >= 1)."""
    opts = [Option("keep")]
    for delta in range(-limits.fmax, limits.fmax + 1):
        if delta and plan.f + delta >= 0 and plan.f + delta + plan.w <= BANDS:
            opts.append(Option("freq", delta))
    for delta in range(-limits.tmax, limits.tmax + 1):
        if delta and plan.s + delta >= 0:
            opts.append(Option("time", delta))
    if plan.cat in limits.gap_categories:
        for delta in range(-limits.gmax, limits.gmax + 1):
            if delta and plan.g + delta >= 1:
                opts.append(Option("gap", delta))
    if limits.allow_cancel:
        opts.append(Option("cancel"))
    return opts


@dataclass
class CellModel:
    """Variables ``y[v]`` (one per plan/action) and the cell rows over which at most one may be chosen."""

    plans: list[Plan]
    options: list[list[Option]]
    var_plan: list[int] = field(default_factory=list)
    var_option: list[int] = field(default_factory=list)
    plan_vars: list[list[int]] = field(default_factory=list)
    rows: list[list[int]] = field(default_factory=list)
    horizon: int = 0
    n_cells: int = 0
    n_rows_raw: int = 0
    memberships: int = 0

    @property
    def n_vars(self) -> int:
        return len(self.var_plan)

    def option_of(self, v: int) -> Option:
        return self.options[self.var_plan[v]][self.var_option[v]]

    def plan_of(self, v: int) -> Plan:
        return self.plans[self.var_plan[v]]


def build_cell_model(plans: list[Plan], options: list[list[Option]]) -> CellModel:
    """Expand every (plan, action) into the cells it occupies; keep rows with >= 2 variables (deduplicated)."""
    model = CellModel(plans, options)
    applied: list[Plan | None] = []
    for i, plan in enumerate(plans):
        model.plan_vars.append([])
        for o, opt in enumerate(options[i]):
            model.plan_vars[i].append(len(model.var_plan))
            model.var_plan.append(i)
            model.var_option.append(o)
            applied.append(opt.apply(plan))
    horizon = max((p.end for p in applied if p is not None), default=0)
    model.horizon = horizon
    cells: dict[int, list[int]] = {}
    memberships = 0
    for v, p in enumerate(applied):
        if p is None:
            continue
        for start, end in p.uses():
            for band in range(p.f, p.f_end):
                base = band * horizon
                for t in range(start, end):
                    cells.setdefault(base + t, []).append(v)
                    memberships += 1
    model.n_cells = len(cells)
    model.memberships = memberships
    raw = [row for row in cells.values() if len(row) >= 2]
    model.n_rows_raw = len(raw)
    model.rows = [list(r) for r in sorted({tuple(row) for row in raw})]
    return model


Level = tuple[str, dict[int, int]]


def _cancel_vars(model: CellModel, cats: tuple[str, ...]) -> dict[int, int]:
    return {v: 1 for v in range(model.n_vars) if model.option_of(v).kind == "cancel" and model.plan_of(v).cat in cats}


def _adjust_vars(model: CellModel, cats: tuple[str, ...]) -> dict[int, int]:
    return {v: 1 for v in range(model.n_vars) if model.option_of(v).is_adjust and model.plan_of(v).cat in cats}


def _amplitude_vars(model: CellModel) -> dict[int, int]:
    return {v: model.option_of(v).amplitude for v in range(model.n_vars) if model.option_of(v).amplitude}


def _merge(*parts: dict[int, int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for part in parts:
        for v, c in part.items():
            out[v] = out.get(v, 0) + c
    return out


def canonical_levels(model: CellModel) -> list[Level]:
    """The seven reporting levels: cancel A/B/C, adjust A/B/C, scaled amplitude (scheme P, MDR-0003)."""
    levels: list[Level] = [(f"cancel{c}", _cancel_vars(model, (c,))) for c in CATEGORIES]
    levels += [(f"adjust{c}", _adjust_vars(model, (c,))) for c in CATEGORIES]
    levels.append(("amplitude", _amplitude_vars(model)))
    return levels


def scheme_levels(name: str, model: CellModel) -> list[Level]:
    """Objective schemes P (primary), T (totals first), S (no priority), W (single weighted sum)."""
    if name == "P":
        return canonical_levels(model)
    if name == "T":
        levels: list[Level] = [("cancel", _cancel_vars(model, CATEGORIES)), ("adjust", _adjust_vars(model, CATEGORIES))]
        levels += [(f"changed{c}", _merge(_cancel_vars(model, (c,)), _adjust_vars(model, (c,)))) for c in CATEGORIES]
        levels.append(("amplitude", _amplitude_vars(model)))
        return levels
    if name == "S":
        return [
            ("cancel", _cancel_vars(model, CATEGORIES)),
            ("adjust", _adjust_vars(model, CATEGORIES)),
            ("amplitude", _amplitude_vars(model)),
        ]
    if name == "W":
        weight = {"A": 3, "B": 2, "C": 1}
        terms: dict[int, int] = {}
        for v in range(model.n_vars):
            opt, plan = model.option_of(v), model.plan_of(v)
            value = 0
            if opt.kind == "cancel":
                value = 100 * weight[plan.cat]
            elif opt.is_adjust:
                value = 30 * weight[plan.cat] + opt.amplitude
            if value:
                terms[v] = value
        return [("weighted", terms)]
    raise KeyError(name)


def level_upper_bounds(model: CellModel, levels: list[Level]) -> list[int]:
    """Upper bound of each level: each plan contributes at most the largest coefficient among its actions."""
    bounds = []
    for _, terms in levels:
        total = 0
        for vars_of_plan in model.plan_vars:
            total += max((terms.get(v, 0) for v in vars_of_plan), default=0)
        bounds.append(int(total))
    return bounds


def separated_weights(bounds: list[int]) -> list[int]:
    """Weights W_k = prod_{j>k} (U_j + 1): a single weighted sum then reproduces the lexicographic optimum."""
    weights = [1] * len(bounds)
    for k in range(len(bounds) - 2, -1, -1):
        weights[k] = weights[k + 1] * (bounds[k + 1] + 1)
    return weights


def evaluate(model: CellModel, chosen: list[int], levels: list[Level]) -> list[int]:
    """Value of every level for a solution given as the chosen variable per plan."""
    chosen_set = set(chosen)
    return [int(sum(c for v, c in terms.items() if v in chosen_set)) for _, terms in levels]


def decisions_from_choice(model: CellModel, chosen: list[int]) -> list[dict[str, Any]]:
    out = []
    for i, plan in enumerate(model.plans):
        opt = model.option_of(chosen[i])
        after = opt.apply(plan)
        out.append(
            {
                "pid": plan.pid,
                "cat": plan.cat,
                "kind": opt.kind,
                "delta": opt.delta,
                "label": opt.label(),
                "plan": after.record() if after is not None else None,
            }
        )
    return out


def table_from_decisions(decisions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    table = {c: {"keep": 0, "adjust": 0, "cancel": 0} for c in CATEGORIES}
    for dec in decisions:
        key = {"keep": "keep", "cancel": "cancel"}.get(dec["kind"], "adjust")
        table[dec["cat"]][key] += 1
    return table


def solve_lexicographic_cpsat(
    model: CellModel,
    levels: list[Level],
    *,
    seed: int,
    workers: int = 8,
    time_limit: float = 600.0,
    hint: list[int] | None = None,
) -> dict[str, Any]:
    """Minimise the levels in order with CP-SAT, fixing each optimum before the next (every level must be OPTIMAL)."""
    from ortools.sat.python import cp_model

    t0 = time.monotonic()
    cp = cp_model.CpModel()
    y = [cp.NewBoolVar(f"y{v}") for v in range(model.n_vars)]
    for vars_of_plan in model.plan_vars:
        cp.AddExactlyOne(y[v] for v in vars_of_plan)
    for row in model.rows:
        cp.AddAtMostOne(y[v] for v in row)
    if hint is not None:
        hinted = set(hint)
        for v in range(model.n_vars):
            cp.AddHint(y[v], v in hinted)
    per_level: list[dict[str, Any]] = []
    values: list[int] = []
    chosen: list[int] | None = None
    all_optimal = True
    for name, terms in levels:
        expr = cp_model.LinearExpr.WeightedSum([y[v] for v in terms], [c for c in terms.values()])
        cp.Minimize(expr)
        solver = cp_model.CpSolver()
        solver.parameters.random_seed = int(seed)
        solver.parameters.num_workers = int(workers)
        solver.parameters.max_time_in_seconds = float(time_limit)
        t1 = time.monotonic()
        status = solver.Solve(cp)
        name_status = solver.StatusName(status)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            per_level.append({"level": name, "status": name_status, "seconds": round(time.monotonic() - t1, 3)})
            all_optimal = False
            break
        value = int(round(solver.ObjectiveValue()))
        values.append(value)
        chosen = [next(v for v in vars_of_plan if solver.Value(y[v])) for vars_of_plan in model.plan_vars]
        per_level.append(
            {
                "level": name,
                "status": name_status,
                "value": value,
                "bound": float(solver.BestObjectiveBound()),
                "seconds": round(time.monotonic() - t1, 3),
                "branches": int(solver.NumBranches()),
                "conflicts": int(solver.NumConflicts()),
            }
        )
        all_optimal = all_optimal and status == cp_model.OPTIMAL
        cp.Add(expr == value)
        cp.ClearHints()
        for v in range(model.n_vars):
            cp.AddHint(y[v], bool(solver.Value(y[v])))
    return {
        "solver": "cp-sat",
        "levels": per_level,
        "vector": values,
        "chosen": chosen,
        "all_optimal": all_optimal,
        "seconds": round(time.monotonic() - t0, 3),
        "n_vars": model.n_vars,
        "n_rows": len(model.rows),
    }


def solve_weighted_cpsat(
    model: CellModel, levels: list[Level], *, seed: int, workers: int = 8, time_limit: float = 600.0
) -> dict[str, Any]:
    """Single CP-SAT solve of the separated-weight scalarisation (must reproduce the lexicographic vector)."""
    from ortools.sat.python import cp_model

    t0 = time.monotonic()
    weights = separated_weights(level_upper_bounds(model, levels))
    terms: dict[int, int] = {}
    for w, (_, lv) in zip(weights, levels):
        for v, c in lv.items():
            terms[v] = terms.get(v, 0) + w * c
    cp = cp_model.CpModel()
    y = [cp.NewBoolVar(f"y{v}") for v in range(model.n_vars)]
    for vars_of_plan in model.plan_vars:
        cp.AddExactlyOne(y[v] for v in vars_of_plan)
    for row in model.rows:
        cp.AddAtMostOne(y[v] for v in row)
    cp.Minimize(cp_model.LinearExpr.WeightedSum([y[v] for v in terms], list(terms.values())))
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_workers = int(workers)
    solver.parameters.max_time_in_seconds = float(time_limit)
    status = solver.Solve(cp)
    chosen = None
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        chosen = [next(v for v in vars_of_plan if solver.Value(y[v])) for vars_of_plan in model.plan_vars]
    return {
        "solver": "cp-sat-weighted",
        "status": solver.StatusName(status),
        "weights": weights,
        "objective": float(solver.ObjectiveValue()) if chosen else None,
        "vector": evaluate(model, chosen, levels) if chosen else None,
        "chosen": chosen,
        "seconds": round(time.monotonic() - t0, 3),
    }


def _highs_base(model: CellModel, *, integer: bool, time_limit: float, seed: int, threads: int) -> Any:
    import highspy
    import numpy as np

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("log_to_console", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("random_seed", int(seed))
    h.setOptionValue("threads", int(threads))
    h.setOptionValue("mip_rel_gap", 0.0)
    h.setOptionValue("mip_abs_gap", 0.0)
    n = model.n_vars
    h.addVars(n, np.zeros(n), np.ones(n))
    if integer:
        h.changeColsIntegrality(n, np.arange(n, dtype=np.int32), np.array([highspy.HighsVarType.kInteger] * n))
    starts, index, lower, upper = [], [], [], []
    nnz = 0
    for vars_of_plan in model.plan_vars:
        starts.append(nnz)
        index.extend(vars_of_plan)
        nnz += len(vars_of_plan)
        lower.append(1.0)
        upper.append(1.0)
    for row in model.rows:
        starts.append(nnz)
        index.extend(row)
        nnz += len(row)
        lower.append(-highspy.kHighsInf)
        upper.append(1.0)
    h.addRows(
        len(starts),
        np.array(lower),
        np.array(upper),
        nnz,
        np.array(starts, dtype=np.int32),
        np.array(index, dtype=np.int32),
        np.ones(nnz),
    )
    return h


def solve_lexicographic_highs(
    model: CellModel, levels: list[Level], *, seed: int, threads: int = 8, time_limit: float = 600.0
) -> dict[str, Any]:
    """Independent cross-check: the same 0-1 model in HiGHS, solved level by level as MILPs, plus the LP
    relaxation bound of every level (previous levels fixed to their integer optima)."""
    import highspy
    import numpy as np

    t0 = time.monotonic()
    n = model.n_vars
    mip = _highs_base(model, integer=True, time_limit=time_limit, seed=seed, threads=threads)
    lp = _highs_base(model, integer=False, time_limit=time_limit, seed=seed, threads=threads)
    per_level: list[dict[str, Any]] = []
    values: list[int] = []
    chosen: list[int] | None = None
    all_optimal = True
    idx_all = np.arange(n, dtype=np.int32)
    for name, terms in levels:
        cost = np.zeros(n)
        for v, c in terms.items():
            cost[v] = c
        entry: dict[str, Any] = {"level": name}
        for tag, h in (("lp", lp), ("mip", mip)):
            h.changeColsCost(n, idx_all, cost)
            t1 = time.monotonic()
            h.run()
            status = h.getModelStatus()
            entry[f"{tag}_status"] = h.modelStatusToString(status)
            entry[f"{tag}_seconds"] = round(time.monotonic() - t1, 3)
            if status == highspy.HighsModelStatus.kOptimal:
                entry[f"{tag}_value"] = float(h.getInfo().objective_function_value)
            elif tag == "mip":
                entry["mip_value"] = float(h.getInfo().objective_function_value)
                entry["mip_bound"] = float(h.getInfo().mip_dual_bound)
        if entry.get("mip_status") != "Optimal":
            all_optimal = False
            per_level.append(entry)
            break
        value = int(round(entry["mip_value"]))
        values.append(value)
        sol = np.array(mip.getSolution().col_value)
        chosen = [int(max(vars_of_plan, key=lambda v: sol[v])) for vars_of_plan in model.plan_vars]
        per_level.append(entry)
        idx = np.array(list(terms), dtype=np.int32)
        val = np.array([float(c) for c in terms.values()])
        for h in (mip, lp):
            h.addRow(float(value), float(value), len(idx), idx, val)
    return {
        "solver": "highs",
        "levels": per_level,
        "vector": values,
        "chosen": chosen,
        "all_optimal": all_optimal,
        "seconds": round(time.monotonic() - t0, 3),
        "version": str(highspy.Highs().version()),
    }
