"""Paper figures and tables for Problem D (stages ``figures`` and ``tables``).

Figures follow the house style in ``forge.plotting`` (vector PDF + PNG preview, Okabe–Ito palette with a
fixed category → hue mapping, one axis per panel, legends whenever two or more series are shown).
Tables are booktabs fragments (``tables/*.tex``) with a CSV twin; the paper wraps them in ``table``.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from typing import Any

from forge import plotting
from forge.context import StageContext
from forge.runner import stage
from forge.tex import tex_escape
from pipelines.d.detect import overlapping_uses, plans_conflict
from pipelines.d.plans import CATEGORIES, Plan, horizon, plan_from_record
from pipelines.d.resolve import Limits, enumerate_options

CAT_COLOR = {"A": "#0072B2", "B": "#D55E00", "C": "#009E73"}  # fixed identity → hue (Okabe–Ito slots 1–3)
ACTION_COLOR = {"freq": "#0072B2", "time": "#E69F00", "gap": "#CC79A7", "cancel": "#000000", "keep": "#BBBBBB"}
ACTION_LABEL = {"freq": "频段平移", "time": "时间平移", "gap": "间隔调整", "cancel": "撤销", "keep": "保持"}
GREY = "#C8C8C8"
REPORT_DEPS = ("detect", "resolve", "pack", "resolve_interval", "bench", "sensitivity")


def _plans(records: list[dict[str, Any]]) -> list[Plan]:
    return [plan_from_record(r) for r in records]


def _rects(
    ax: Any,
    plans: Sequence[Plan],
    face: dict[str, str],
    *,
    edge: dict[str, str] | None = None,
    hatch_ids: set[str] = frozenset(),
    alpha: float = 0.9,
) -> None:
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle

    edge = edge or {}
    plain, plain_face, plain_edge, plain_lw = [], [], [], []
    hatched, hatched_edge = [], []
    for p in plans:
        for start, end in p.uses():
            rect = Rectangle((start, p.f), end - start, p.w)
            if p.pid in hatch_ids:
                hatched.append(rect)
                hatched_edge.append(edge.get(p.pid, "#000000"))
            else:
                plain.append(rect)
                plain_face.append(face.get(p.pid, GREY))
                plain_edge.append(edge.get(p.pid, "none"))
                plain_lw.append(0.6 if p.pid in edge else 0.0)
    if plain:
        ax.add_collection(
            PatchCollection(plain, facecolors=plain_face, edgecolors=plain_edge, linewidths=plain_lw, alpha=alpha)
        )
    if hatched:
        ax.add_collection(
            PatchCollection(hatched, facecolors="none", edgecolors=hatched_edge, linewidths=0.6, hatch="////")
        )


def _plane(ax: Any, horizon_t: int, *, xlabel: bool = True) -> None:
    ax.set_xlim(0, horizon_t)
    ax.set_ylim(0, 100)
    ax.set_ylabel("频段编号 (Δf)")
    if xlabel:
        ax.set_xlabel("时间 (Δt)")
    ax.grid(False)


def _legend(ax: Any, entries: list[tuple[str, str, str | None]], **kwargs: Any) -> None:
    from matplotlib.patches import Patch

    handles = [
        Patch(
            # colour "none" means the mark is drawn by its edge only (e.g. the black outline used for
            # conflicting uses): give the swatch a white face and a black edge so that it is visible.
            facecolor="white" if color == "none" else (color if hatch is None else "none"),
            edgecolor="#000000" if (hatch or color == "none") else "none",
            hatch=hatch or None,
            label=label,
        )
        for label, color, hatch in entries
    ]
    ax.legend(handles=handles, frameon=False, **kwargs)


def _conflict_use_ids(plans: list[Plan], conflicts: list[dict[str, Any]]) -> set[tuple[str, int]]:
    by_id = {p.pid: p for p in plans}
    out: set[tuple[str, int]] = set()
    for rec in conflicts:
        a, b = by_id[rec["id1"]], by_id[rec["id2"]]
        for k, l in overlapping_uses(a, b):
            out.add((a.pid, k))
            out.add((b.pid, l))
    return out


def fig_q1_gantt(ctx: StageContext, plans: list[Plan], conflicts: list[dict[str, Any]]) -> None:
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle

    horizon_t = horizon(plans)
    fig, ax = plotting.new_figure(6.5, 3.4)
    _rects(ax, plans, {p.pid: CAT_COLOR[p.cat] for p in plans}, alpha=0.75)
    hot = _conflict_use_ids(plans, conflicts)
    patches = [
        Rectangle((start, p.f), end - start, p.w)
        for p in plans
        for k, (start, end) in enumerate(p.uses())
        if (p.pid, k) in hot
    ]
    ax.add_collection(PatchCollection(patches, facecolors="none", edgecolors="#000000", linewidths=0.7))
    _plane(ax, horizon_t)
    _legend(
        ax,
        [
            ("A 类", CAT_COLOR["A"], None),
            ("B 类", CAT_COLOR["B"], None),
            ("C 类", CAT_COLOR["C"], None),
            ("冲突的使用次（黑边）", "none", ""),
        ],
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
        ncol=1,
    )
    plotting.save(fig, ctx.out("figures", "fig_q1_gantt.pdf"))


def fig_q1_structure(ctx: StageContext, stats: dict[str, Any]) -> None:
    import numpy as np

    fig, axes = plotting.new_figure(6.5, 2.7, ncols=2, gridspec_kw={"width_ratios": [1.0, 1.4]})
    ax = axes[0]
    matrix = np.zeros((3, 3))
    for key, value in stats["by_pair"].items():
        i, j = CATEGORIES.index(key[0]), CATEGORIES.index(key[1])
        matrix[i, j] = value
        matrix[j, i] = value
    ax.imshow(matrix, cmap="Blues", vmin=0)
    for i in range(3):
        for j in range(3):
            ax.text(
                j,
                i,
                f"{int(matrix[i, j])}",
                ha="center",
                va="center",
                color="#000000" if matrix[i, j] < matrix.max() * 0.6 else "#FFFFFF",
            )
    ax.set_xticks(range(3), [f"{c} 类" for c in CATEGORIES])
    ax.set_yticks(range(3), [f"{c} 类" for c in CATEGORIES])
    ax.set_title("(a) 冲突对数（按类别对）")
    ax.grid(False)
    ax = axes[1]
    hist = {int(k): v for k, v in stats["degree_hist"].items()}
    degrees = sorted(hist)
    ax.bar(degrees, [hist[d] for d in degrees], color="#0072B2", width=0.8)
    for d in degrees:
        ax.text(d, hist[d], str(hist[d]), ha="center", va="bottom", fontsize=7)
    ax.set_xlabel("冲突图中的度（与之冲突的计划数）")
    ax.set_ylabel("计划数量")
    ax.set_title("(b) 度分布")
    ax.set_xticks(degrees)
    plotting.save(fig, ctx.out("figures", "fig_q1_structure.pdf"))


def fig_resolution(
    ctx: StageContext,
    name: str,
    plans: list[Plan],
    decisions: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    title: str,
) -> None:
    from matplotlib.patches import FancyArrowPatch

    horizon_t = max(horizon(plans), max((plan_from_record(d["plan"]).end for d in decisions if d["plan"]), default=0))
    fig, axes = plotting.new_figure(6.5, 5.2, nrows=2, sharex=True)
    kinds = {d["pid"]: d["kind"] for d in decisions}
    ax = axes[0]
    face = {p.pid: (ACTION_COLOR[kinds[p.pid]] if kinds[p.pid] in {"freq", "time", "gap"} else GREY) for p in plans}
    _rects(ax, [p for p in plans if kinds[p.pid] != "cancel"], face, alpha=0.85)
    _rects(
        ax,
        [p for p in plans if kinds[p.pid] == "cancel"],
        {},
        hatch_ids={p.pid for p in plans if kinds[p.pid] == "cancel"},
    )
    hot = _conflict_use_ids(plans, conflicts)
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle

    ax.add_collection(
        PatchCollection(
            [Rectangle((s, p.f), e - s, p.w) for p in plans for k, (s, e) in enumerate(p.uses()) if (p.pid, k) in hot],
            facecolors="none",
            edgecolors="#000000",
            linewidths=0.5,
        )
    )
    _plane(ax, horizon_t, xlabel=False)
    ax.set_title(f"(a) 消解前：{title}中被调整/撤销的计划以颜色标出，黑边为冲突使用次")
    _legend(
        ax,
        [
            ("保持", GREY, None),
            ("频段平移", ACTION_COLOR["freq"], None),
            ("时间平移", ACTION_COLOR["time"], None),
            ("间隔调整", ACTION_COLOR["gap"], None),
            ("撤销", "none", "////"),
        ],
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
    )
    ax = axes[1]
    after = [plan_from_record(d["plan"]) for d in decisions if d["plan"]]
    _rects(
        ax, after, {p.pid: (ACTION_COLOR[kinds[p.pid]] if kinds[p.pid] != "keep" else GREY) for p in after}, alpha=0.85
    )
    by_id = {p.pid: p for p in plans}
    for p in after:
        if kinds[p.pid] in {"freq", "time"}:
            before = by_id[p.pid]
            ax.add_patch(
                FancyArrowPatch(
                    (before.s, before.f + before.w / 2),
                    (p.s, p.f + p.w / 2),
                    arrowstyle="-|>",
                    mutation_scale=6,
                    color="#000000",
                    linewidth=0.5,
                    alpha=0.6,
                )
            )
    _plane(ax, horizon_t)
    ax.set_title("(b) 消解后：无冲突的用频计划（箭头为平移方向）")
    plotting.save(fig, ctx.out("figures", f"{name}.pdf"))


def fig_schemes(ctx: StageContext, name: str, alternatives: dict[str, Any]) -> None:
    import numpy as np

    names = [n for n in ("P", "T", "S", "W") if alternatives.get(n, {}).get("canonical_vector")]
    fig, axes = plotting.new_figure(6.5, 2.6, ncols=2)
    ax = axes[0]
    x = np.arange(len(names))
    bottom = np.zeros(len(names))
    for idx, c in enumerate(CATEGORIES):
        vals = np.array([alternatives[n]["canonical_vector"][3 + idx] for n in names], dtype=float)
        ax.bar(x, vals, bottom=bottom, color=CAT_COLOR[c], label=f"{c} 类调整", width=0.6)
        bottom += vals
    for i in range(len(names)):
        ax.text(x[i], bottom[i], str(int(bottom[i])), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, [f"方案 {n}" for n in names])
    ax.set_ylabel("被调整的计划数")
    ax.set_title("(a) 各目标方案的调整数量")
    ax.set_ylim(0, float(bottom.max()) * 1.3)
    ax.legend(frameon=False, fontsize=7, ncol=3, loc="upper left")
    ax = axes[1]
    amps = [alternatives[n]["canonical_vector"][6] / 10.0 for n in names]
    ax.bar(x, amps, color="#0072B2", width=0.6)
    for i, a in enumerate(amps):
        ax.text(x[i], a, f"{a:.1f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, [f"方案 {n}" for n in names])
    ax.set_ylabel("归一化总调整幅度")
    ax.set_title("(b) 总调整幅度")
    plotting.save(fig, ctx.out("figures", f"{name}.pdf"))


def fig_q3_layout(
    ctx: StageContext,
    existing: list[Plan],
    new_plans: list[Plan],
    horizon_t: int,
    *,
    name: str = "fig_q3_layout",
    title: str | None = None,
) -> None:
    fig, ax = plotting.new_figure(6.5, 3.4)
    _rects(ax, existing, {p.pid: GREY for p in existing}, alpha=0.9)
    _rects(ax, new_plans, {p.pid: CAT_COLOR["C"] for p in new_plans}, alpha=0.95)
    _plane(ax, horizon_t)
    if title:
        ax.set_title(title)
    _legend(
        ax,
        [("既有计划", GREY, None), (f"新增 C 类计划（{len(new_plans)} 个）", CAT_COLOR["C"], None)],
        loc="upper left",
        bbox_to_anchor=(1.0, 1.0),
    )
    plotting.save(fig, ctx.out("figures", f"{name}.pdf"))


def fig_q4_comparison(
    ctx: StageContext, q2_table: dict[str, Any], q4_table: dict[str, Any], q4_shifts: dict[str, Any]
) -> None:
    import numpy as np

    fig, axes = plotting.new_figure(6.5, 2.6, ncols=2)
    ax = axes[0]
    x = np.arange(3)
    width = 0.36
    q2 = [q2_table[c]["adjust"] for c in CATEGORIES]
    q4 = [q4_table[c]["adjust"] for c in CATEGORIES]
    ax.bar(x - width / 2, q2, width, color="#0072B2", label="问题 2")
    ax.bar(x + width / 2, q4, width, color="#D55E00", label="问题 4")
    for i in range(3):
        ax.text(x[i] - width / 2, q2[i], str(q2[i]), ha="center", va="bottom", fontsize=7)
        ax.text(x[i] + width / 2, q4[i], str(q4[i]), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, [f"{c} 类" for c in CATEGORIES])
    ax.set_ylabel("被调整的计划数")
    ax.set_title("(a) 调整数量对照")
    ax.legend(frameon=False)
    ax = axes[1]
    kinds = ["freq", "time", "gap", "cancel"]
    counts = [q4_shifts[k]["count"] if k != "cancel" else q4_shifts["cancel"] for k in kinds]
    ax.bar(range(4), counts, color=[ACTION_COLOR[k] for k in kinds], width=0.6)
    for i, v in enumerate(counts):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(4), [ACTION_LABEL[k] for k in kinds])
    ax.set_ylabel("计划数")
    ax.set_title("(b) 问题 4 的动作构成")
    plotting.save(fig, ctx.out("figures", "fig_q4_comparison.pdf"))


def fig_bench_scaling(ctx: StageContext, scaling: list[dict[str, Any]]) -> None:
    from matplotlib.ticker import NullFormatter

    fig, ax = plotting.new_figure(6.3, 3.0)
    ns = [r["n"] for r in scaling]
    limit = max((r["cpsat_seconds"] for r in scaling), default=0.0)
    series = [
        ("成对枚举检测", [r["pairwise_seconds"] for r in scaling], "#0072B2", "o"),
        ("分桶扫描线检测", [r["sweep_seconds"] for r in scaling], "#D55E00", "s"),
        ("单元格模型构建", [r["build_seconds"] for r in scaling], "#009E73", "^"),
        (
            f"CP-SAT 消解（固定时限 {limit:.0f} s，到时返回可行解）",
            [r["cpsat_seconds"] for r in scaling],
            "#E69F00",
            "D",
        ),
    ]
    for label, ys, color, marker in series:
        ax.plot(ns, ys, marker=marker, markersize=4, color=color, label=label)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("计划数量 n（合成实例）")
    ax.set_ylabel("耗时 (s)")
    ax.set_xticks(ns, [str(n) for n in ns])
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.legend(frameon=False, fontsize=7, loc="center left")
    ax.set_xlim(ns[0] * 0.9, ns[-1] * 1.1)
    plotting.save(fig, ctx.out("figures", "fig_bench_scaling.pdf"))


def fig_sensitivity(ctx: StageContext, cases: list[dict[str, Any]]) -> None:
    import numpy as np

    rows = [r for r in cases if r["adjust_total"] is not None]
    labels = [f"({r['fmax']},{r['tmax']})" for r in rows]
    x = np.arange(len(rows))
    fig, axes = plotting.new_figure(6.5, 2.7, ncols=2)
    ax = axes[0]
    bottom = np.zeros(len(rows))
    for idx, c in enumerate(CATEGORIES):
        vals = np.array([r["vector"][3 + idx] for r in rows], dtype=float)
        ax.bar(x, vals, bottom=bottom, color=CAT_COLOR[c], label=f"{c} 类调整", width=0.65)
        bottom += vals
    cancels = np.array([r["cancel_total"] for r in rows], dtype=float)
    ax.bar(x, cancels, bottom=bottom, color="#000000", label="撤销", width=0.65)
    for i in range(len(rows)):
        ax.text(x[i], bottom[i] + cancels[i], str(int(bottom[i] + cancels[i])), ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, labels, rotation=45, ha="right")
    ax.set_xlabel("最大平移幅度 (频段, 时间)")
    ax.set_ylabel("被调整/撤销的计划数")
    ax.set_title("(a) 调整与撤销数量")
    ax.set_ylim(0, float((bottom + cancels).max()) * 1.35)
    ax.legend(frameon=False, fontsize=7, ncol=2, loc="upper left")
    ax = axes[1]
    ax.bar(x, [r["amplitude"] for r in rows], color="#0072B2", width=0.65)
    for i, r in enumerate(rows):
        ax.text(x[i], r["amplitude"], f"{r['amplitude']:.1f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, labels, rotation=45, ha="right")
    ax.set_xlabel("最大平移幅度 (频段, 时间)")
    ax.set_ylabel("归一化总调整幅度")
    ax.set_title("(b) 总调整幅度")
    plotting.save(fig, ctx.out("figures", "fig_sensitivity.pdf"))


@stage("figures", deps=REPORT_DEPS, description="Paper figures (vector PDF + PNG preview)")
def figures(ctx: StageContext) -> dict[str, Any]:
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    conflicts = ctx.dep_data("detect", "conflicts.json")
    stats = ctx.dep_data("detect", "stats.json")
    fig_q1_gantt(ctx, plans, conflicts)
    fig_q1_structure(ctx, stats)
    q2_dec = ctx.dep_data("resolve", "decisions.json")
    fig_resolution(ctx, "fig_q2_resolution", plans, q2_dec, conflicts, "问题 2")
    fig_schemes(ctx, "fig_q2_schemes", ctx.dep_data("resolve", "alternatives.json"))
    existing = _plans(ctx.dep_data("resolve", "resolved_plans.json"))
    new_plans = _plans(ctx.dep_data("pack", "new_plans.json"))
    pack_report = ctx.dep_data("pack", "pack_report.json")
    fig_q3_layout(ctx, existing, new_plans, int(pack_report["horizon"]))
    if "repack" in pack_report.get("alternatives", {}):
        repack = ctx.dep_data("pack", "repack_plans.json")
        fig_q3_layout(
            ctx,
            _plans(repack["existing"]),
            _plans(repack["new"]),
            int(pack_report["horizon"]),
            name="fig_q3_repack",
            title="既有计划经首次适配重排后（MDR-0010 解释 B）",
        )
    q4_dec = ctx.dep_data("resolve_interval", "decisions.json")
    fig_resolution(ctx, "fig_q4_resolution", plans, q4_dec, conflicts, "问题 4")
    q2_rep = ctx.dep_data("resolve", "solver_report.json")
    q4_rep = ctx.dep_data("resolve_interval", "solver_report.json")
    fig_q4_comparison(ctx, q2_rep["table"], q4_rep["table"], q4_rep["shifts"])
    fig_bench_scaling(ctx, ctx.dep_data("bench", "scaling.json"))
    fig_sensitivity(ctx, ctx.dep_data("sensitivity", "cases.json"))
    files = sorted(p.name for p in (ctx.stage_dir / "figures").glob("*.pdf"))
    ctx.number("FigureCount", len(files))
    return {"figures": files}


# ---------------------------------------------------------------------------------------------- tables
def _write_table(
    ctx: StageContext,
    name: str,
    header: list[str],
    rows: list[list[Any]],
    *,
    align: str | None = None,
    long: bool = False,
) -> None:
    def cell(v: Any) -> str:
        if isinstance(v, float):
            return f"{v:.4f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{v:.0f}"
        return tex_escape(str(v))

    align = align or ("l" + "r" * (len(header) - 1))
    lines = []
    if long:
        lines.append(f"\\begin{{longtable}}{{@{{}}{align}@{{}}}}")
        lines.append(
            "\\toprule "
            + " & ".join(tex_escape(h) for h in header)
            + " \\\\ \\midrule \\endhead \\bottomrule \\endfoot"
        )
        lines += [" & ".join(cell(v) for v in row) + " \\\\" for row in rows]
        lines.append("\\end{longtable}")
    else:
        lines.append(f"\\begin{{tabular}}{{@{{}}{align}@{{}}}}")
        lines.append("\\toprule")
        lines.append(" & ".join(tex_escape(h) for h in header) + " \\\\")
        lines.append("\\midrule")
        lines += [" & ".join(cell(v) for v in row) + " \\\\" for row in rows]
        lines.append("\\bottomrule")
        lines.append("\\end{tabular}")
    ctx.out("tables", f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with ctx.out("tables", f"{name}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _table1(table: dict[str, dict[str, int]]) -> list[list[Any]]:
    rows = [[f"{c} 类", table[c]["keep"], table[c]["adjust"], table[c]["cancel"]] for c in CATEGORIES]
    rows.append(
        [
            "合计",
            sum(table[c]["keep"] for c in CATEGORIES),
            sum(table[c]["adjust"] for c in CATEGORIES),
            sum(table[c]["cancel"] for c in CATEGORIES),
        ]
    )
    return rows


def _vector_text(vec: list[int] | None) -> str:
    return "(" + ", ".join(str(v) for v in vec) + ")" if vec else "-"


def _adjustment_rows(plans: list[Plan], decisions: list[dict[str, Any]], with_gap: bool) -> list[list[Any]]:
    by_id = {p.pid: p for p in plans}
    rows = []
    for dec in sorted(decisions, key=lambda d: d["pid"]):
        if dec["kind"] == "keep":
            continue
        before = by_id[dec["pid"]]
        after = plan_from_record(dec["plan"]) if dec["plan"] else None
        row = [
            dec["pid"],
            ACTION_LABEL[dec["kind"]],
            before.freq_text(),
            after.freq_text() if after else "-",
            before.time_text(),
            after.time_text() if after else "-",
        ]
        if with_gap:
            row += [before.g, after.g if after else "-"]
        rows.append(row)
    return rows


def _cancelled_rows(
    plans: list[Plan],
    decisions: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    limits: Limits,
) -> list[list[Any]]:
    """Why a plan was cancelled.

    The original conflict degree is *not* the binding reason — after the other plans move, the relevant
    neighbourhood is a different one. The last column therefore counts the plan's legal single-parameter
    actions that would leave it conflict-free **against the reported solution**; it is that count being
    zero, not the degree, that forces the cancellation."""
    by_id = {p.pid: p for p in plans}
    neighbours: dict[str, list[str]] = {p.pid: [] for p in plans}
    for rec in conflicts:
        neighbours[rec["id1"]].append(rec["id2"])
        neighbours[rec["id2"]].append(rec["id1"])
    survivors = [plan_from_record(d["plan"]) for d in decisions if d.get("plan")]
    rows = []
    for dec in sorted(decisions, key=lambda d: d["pid"]):
        if dec["kind"] != "cancel":
            continue
        plan = by_id[dec["pid"]]
        nbrs = neighbours[plan.pid]
        actions = [o for o in enumerate_options(plan, limits) if o.kind not in {"keep", "cancel"}]
        free = 0
        for opt in actions:
            after = opt.apply(plan)
            if after is not None and not any(plans_conflict(after, q) for q in survivors):
                free += 1
        rows.append(
            [
                plan.pid,
                plan.freq_text(),
                plan.time_text(),
                len(nbrs),
                sum(1 for n in nbrs if by_id[n].cat in {"A", "B"}),
                len(actions),
                free,
            ]
        )
    return rows


def _conditional_table(ctx: StageContext, tag: str, rep: dict[str, Any]) -> None:
    """Per-level evidence of the conditional problem (MDR-0012): the *set* of cancelled plans is fixed
    to the reported solution and only the adjustment and amplitude levels are minimised. A bound proved
    here bounds that restriction, never the unrestricted lexicographic optimum. No-op when the stage ran
    without ``conditional_time_limits``."""
    cond = rep.get("conditional") or {}
    levels = cond.get("levels") or []
    if not levels:
        return
    rows = [
        [
            entry["level"],
            entry.get("value", "-"),
            f"{entry['bound']:.2f}" if "bound" in entry else "-",
            entry.get("status", "-"),
            f"{entry.get('seconds', 0):.1f}",
        ]
        for entry in levels
    ]
    _write_table(
        ctx,
        f"tab_{tag}_conditional",
        ["目标层级", "值", "已证明下界", "状态", "用时/s"],
        rows,
        align="lrrlr",
    )


def _solver_tables(ctx: StageContext, tag: str, rep: dict[str, Any]) -> None:
    """Per-level solver evidence (CP-SAT value/bound/status, HiGHS LP and MILP bounds) and model statistics."""
    solver_rows = []
    highs_levels = {e["level"]: e for e in rep["highs"]["levels"]}
    for entry in rep["primary"]["levels"]:
        h = highs_levels.get(entry["level"], {})
        solver_rows.append(
            [
                entry["level"],
                entry.get("value", "-"),
                f"{entry['bound']:.2f}" if "bound" in entry else "-",
                entry.get("status", "-"),
                f"{entry.get('seconds', 0):.1f}",
                f"{h['lp_value']:.2f}" if "lp_value" in h else "-",
                f"{h['mip_value']:.0f}" if "mip_value" in h and h["mip_value"] < 1e20 else "-",
                f"{h['mip_bound']:.2f}" if "mip_bound" in h and abs(h["mip_bound"]) < 1e20 else "-",
                h.get("mip_status", "-"),
            ]
        )
    _write_table(
        ctx,
        f"tab_{tag}_solver",
        [
            "目标层级",
            "CP-SAT 值",
            "CP-SAT 下界",
            "CP-SAT 状态",
            "用时/s",
            "HiGHS LP 下界",
            "HiGHS MILP 值",
            "HiGHS MILP 下界",
            "HiGHS 状态",
        ],
        solver_rows,
        align="lrrlrrrrl",
    )
    m = rep["model"]
    _write_table(
        ctx,
        f"tab_{tag}_model",
        ["项目", "数值"],
        [
            ["决策变量数（计划-动作对）", m["vars"]],
            ["时频单元数（含动作扩展）", m["cells"]],
            ["变量-单元隶属数", m["memberships"]],
            ["单元格 AtMostOne 约束数（去重前 / 去重后）", f"{m['rows_raw']} / {m['rows']}"],
            [
                "成对蕴含团约束数 / 强制撤销割数",
                f"{m.get('strengthening_groups', 0)} / {m.get('forced_cancel_pairs', 0)}",
            ],
            ["可能相互冲突的计划对数", m.get("interacting_pairs", "-")],
            [
                "每计划最多动作数（A/B/C）",
                f"{m['options_per_plan']['A']}/{m['options_per_plan']['B']}/{m['options_per_plan']['C']}",
            ],
            ["CP-SAT 词典序总用时/s", f"{rep['primary']['seconds']:.1f}"],
            ["热启动现任解目标向量（MDR-0009）", _vector_text(rep.get("hint", {}).get("vector"))],
            [
                "词典序求解起点",
                {"file": "仓库内现任解", "weighted": "分离权重解"}.get(rep.get("hint", {}).get("start_from"), "冷启动"),
            ],
            ["各级均证明最优", "是" if rep.get("all_optimal") else "否"],
            ["HiGHS 交叉验证总用时/s", f"{rep['highs']['seconds']:.1f}"],
            ["HiGHS 证明最优的各级与 CP-SAT 一致", "是" if rep["highs_agree"] else "否"],
            ["分离权重单目标解与词典序向量一致", "是" if rep["weighted_agree"] else "否"],
        ],
        align="lr",
    )
    _conditional_table(ctx, tag, rep)


@stage("tables", deps=REPORT_DEPS, description="Paper tables (booktabs .tex + CSV)")
def tables(ctx: StageContext) -> dict[str, Any]:
    plans = _plans(ctx.dep_data("detect", "plans.json"))
    stats = ctx.dep_data("detect", "stats.json")
    conflicts = ctx.dep_data("detect", "conflicts.json")

    # Given data, per category. The table asserts homogeneity instead of assuming it, so that the
    # paper may quote one (w, d, g, n) per class only when every plan of that class really shares it.
    data_rows = []
    for cat in CATEGORIES:
        group = [p for p in plans if p.cat == cat]
        if not group:
            continue
        shapes = {(p.w, p.d, p.g, p.n) for p in group}
        if len(shapes) != 1:
            raise RuntimeError(f"category {cat} is not homogeneous: {sorted(shapes)}")
        head = group[0]
        data_rows.append(
            [
                f"{cat} 类",
                len(group),
                head.w,
                head.d,
                head.g,
                head.n,
                head.period,
                head.d + (head.n - 1) * head.period,
                head.n_cells,
                len(group) * head.n_cells,
            ]
        )
        ctx.number(f"DataPlans{cat}", len(group))
        ctx.number(f"DataWidth{cat}", head.w)
        ctx.number(f"DataDuration{cat}", head.d)
        ctx.number(f"DataGap{cat}", head.g)
        ctx.number(f"DataUses{cat}", head.n)
        ctx.number(f"DataCells{cat}", head.n_cells)
    _write_table(
        ctx,
        "tab_data",
        [
            "类别",
            "装备数/个",
            "频宽 w/Δf",
            "时长 d/Δt",
            "间隔 g/Δt",
            "次数 n/次",
            "周期 (d+g)/Δt",
            "时间跨度/Δt",
            "单计划单元数/单元",
            "该类单元合计/单元",
        ],
        data_rows,
        align="lrrrrrrrrr",
    )

    _write_table(
        ctx,
        "tab_q1_summary",
        ["统计量", "数值"],
        [
            [
                "用频计划数（A/B/C）",
                f"{stats['plans_by_cat']['A']}/{stats['plans_by_cat']['B']}/{stats['plans_by_cat']['C']}",
            ],
            ["冲突对数", stats["pairs"]],
            [
                "相交的使用次对数 / 参与冲突的使用次数 / 使用次总数",
                f"{stats['use_pairs']} / {stats['uses_in_conflict']} / {stats['uses_total']}",
            ],
            [
                "卷入冲突的计划数（A/B/C）",
                f"{stats['plans_involved']}（{stats['plans_involved_by_cat']['A']}/"
                f"{stats['plans_involved_by_cat']['B']}/{stats['plans_involved_by_cat']['C']}）",
            ],
            ["与任何计划都不冲突的孤立计划数", stats["isolated_plans"]],
            ["冲突图连通分量数（不少于 2 个节点）", stats["components"]],
            ["最大连通分量规模", stats["largest_component"]],
            ["最大度 / 平均度", f"{stats['max_degree']} / {stats['mean_degree']:.2f}"],
            ["冲突图密度", f"{stats['density']:.4f}"],
            [
                "时频单元总数 / 被占用 / 重叠",
                f"{stats['cells_total']} / {stats['cells_occupied']} / {stats['cells_overlap']}",
            ],
            ["时间范围（最晚结束时刻，Δt）", stats["horizon"]],
            [
                "冲突图独立数 α(G)（状态）",
                f"{stats['max_independent_set']['value']}（{stats['max_independent_set']['status']}）",
            ],
            ["由此得到的被触动计划数下界 n − α(G)", len(plans) - stats["max_independent_set"]["value"]],
        ],
        align="lr",
    )
    matrix = [[f"{a} 类"] + [stats["by_pair"]["".join(sorted((a, b)))] for b in CATEGORIES] for a in CATEGORIES]
    _write_table(ctx, "tab_q1_category", ["类别", "A 类", "B 类", "C 类"], matrix)
    _write_table(
        ctx,
        "tab_q1_top_degree",
        ["装备编号", "冲突计划数（度）"],
        [[r["pid"], r["degree"]] for r in stats["top_degree"]],
    )
    mult = stats["use_pair_multiplicity"]
    _write_table(ctx, "tab_q1_multiplicity", ["冲突使用次对数 k", "冲突对数量"], [[k, v] for k, v in mult.items()])
    _write_table(
        ctx,
        "tab_q1_conflicts",
        ["序号", "装备 1", "装备 2", "类别对", "冲突使用次对数", "频段重叠宽度"],
        [
            [k, r["id1"], r["id2"], r["pair"], r["use_pairs"], r["band_overlap"]]
            for k, r in enumerate(sorted(conflicts, key=lambda r: (r["id1"], r["id2"])), start=1)
        ],
        align="rlllrr",
        long=True,
    )

    q2 = ctx.dep_data("resolve", "solver_report.json")
    q2_alt = ctx.dep_data("resolve", "alternatives.json")
    q2_dec = ctx.dep_data("resolve", "decisions.json")
    _write_table(ctx, "tab_q2_table1", ["类别", "保留数量", "调整数量", "撤销数量"], _table1(q2["table"]))
    _write_table(
        ctx,
        "tab_q2_adjustments",
        ["装备编号", "动作", "原频段", "新频段", "原首次时间", "新首次时间"],
        _adjustment_rows(plans, q2_dec, False),
        align="llllll",
        long=True,
    )
    scheme_rows = []
    for name, label in (
        ("P", "P：类别内嵌七级词典序（主方案）"),
        ("T", "T：总量优先"),
        ("S", "S：不含优先级"),
        ("W", "W：纯加权和"),
    ):
        alt = q2_alt.get(name)
        if not alt or not alt["canonical_vector"]:
            continue
        v = alt["canonical_vector"]
        scheme_rows.append(
            [
                label,
                f"{v[0]}/{v[1]}/{v[2]}",
                f"{v[3]}/{v[4]}/{v[5]}",
                sum(v[3:6]),
                f"{v[6] / 10:.1f}",
                f"{alt.get('budget_seconds', 0):.0f}",
                f"{alt['seconds']:.1f}",
                "是" if alt["all_optimal"] else "否",
                "通过" if alt["validator_ok"] else "未通过",
            ]
        )
    _write_table(
        ctx,
        "tab_q2_schemes",
        ["目标方案", "撤销 A/B/C", "调整 A/B/C", "调整合计", "归一化幅度", "预算/s", "用时/s", "各级最优", "独立校验"],
        scheme_rows,
        align="lrrrrrrcc",
    )
    _solver_tables(ctx, "q2", q2)
    _write_table(
        ctx,
        "tab_q2_cancelled",
        ["装备编号", "频段", "首次时间", "原冲突邻居数", "其中 A/B 类", "合法平移动作数", "其中在本方案下无冲突"],
        _cancelled_rows(
            plans, q2_dec, conflicts, Limits(fmax=int(q2["limits"]["fmax"]), tmax=int(q2["limits"]["tmax"]))
        ),
        align="lllrrrr",
    )

    pack = ctx.dep_data("pack", "pack_report.json")
    new_plans = _plans(ctx.dep_data("pack", "new_plans.json"))
    bounds = pack["bounds"]
    pack_rows = [
        ["时间范围 T_end（问题 2 方案最晚结束时刻）", pack["horizon"]],
        ["既有计划数 / 占用单元 / 自由单元", f"{pack['existing']} / {pack['cells_occupied']} / {pack['free_cells']}"],
        ["候选放置位置数 (f,s)", pack["candidates"]],
        ["AtMostOne 约束数", pack["rows"]],
        ["贪心下界", pack["greedy"]],
        ["CP-SAT 最优解数量（状态）", f"{pack['cpsat']['value']}（{pack['cpsat']['status']}）"],
        ["CP-SAT 上界", bounds.get("cpsat", "-")],
        ["HiGHS LP 松弛上界", bounds.get("lp", "-")],
        [
            "HiGHS MILP 解 / 上界",
            f"{int(pack['highs_mip']['value'])} / {bounds.get('highs_mip', '-')}" if pack.get("highs_mip") else "-",
        ],
        ["自由单元容量界 floor(自由单元数/72)", bounds["free_cells"]],
        ["逐频段容量界", bounds["per_band"]],
        ["空区域容量界（无既有计划）", pack["empty_region_bound"]],
        ["最终结果 / 最紧上界 / gap", f"{pack['value']} / {pack['upper_bound']} / {pack['gap']}"],
        ["时频利用率（前 / 后）", f"{100 * pack['utilisation_before']:.1f}% / {100 * pack['utilisation_after']:.1f}%"],
    ]
    if pack.get("alternatives", {}).get("original_horizon"):
        alt = pack["alternatives"]["original_horizon"]
        pack_rows.append(
            [f"备选：T_end 取原始计划最晚结束时刻 {alt['horizon']}", f"{alt['value']}（上界 {alt['upper_bound']}）"]
        )
    if pack.get("alternatives", {}).get("repack"):
        rep = pack["alternatives"]["repack"]
        pack_rows.append(
            [
                "备选解释 B（既有计划可任意平移，MDR-0010）：下界 / 上界",
                f"{rep['value']} / {rep['bounds']['free_cells']}（重排移动 {rep['existing_moved']} 个既有计划）",
            ]
        )
    _write_table(ctx, "tab_q3_summary", ["项目", "数值"], pack_rows, align="lr")
    _write_table(
        ctx,
        "tab_q3_plans",
        ["序号", "频段区间", "首次时间区间", "间隔时长", "使用次数"],
        [[k, p.freq_text(), p.time_text(), p.g, p.n] for k, p in enumerate(new_plans, start=1)],
        align="rllrr",
        long=True,
    )
    layouts = pack.get("layouts") or []
    if layouts:
        _write_table(
            ctx,
            "tab_q3_layouts",
            [
                "问题 2 方案",
                "撤销数",
                "存留计划数",
                "时间范围/Δt",
                "自由单元数",
                "可再安排 C 类数",
                "上界",
                "CP-SAT 状态",
                "独立校验",
            ],
            [
                [
                    r["scheme"],
                    r["cancelled"],
                    r["survivors"],
                    r["horizon"],
                    r["free_cells"],
                    r["new_plans"],
                    r["bound"],
                    r["status"],
                    "通过" if r["validator_ok"] else "未通过",
                ]
                for r in layouts
            ],
            align="lrrrrrrlc",
        )

    q4 = ctx.dep_data("resolve_interval", "solver_report.json")
    q4_dec = ctx.dep_data("resolve_interval", "decisions.json")
    q4_alt = ctx.dep_data("resolve_interval", "alternatives.json")
    _write_table(ctx, "tab_q4_table1", ["类别", "保留数量", "调整数量", "撤销数量"], _table1(q4["table"]))
    cmp_rows = [
        [
            f"{c} 类",
            q2["table"][c]["keep"],
            q4["table"][c]["keep"],
            q2["table"][c]["adjust"],
            q4["table"][c]["adjust"],
            q2["table"][c]["cancel"],
            q4["table"][c]["cancel"],
        ]
        for c in CATEGORIES
    ]
    cmp_rows.append(
        [
            "合计",
            sum(q2["table"][c]["keep"] for c in CATEGORIES),
            sum(q4["table"][c]["keep"] for c in CATEGORIES),
            sum(q2["table"][c]["adjust"] for c in CATEGORIES),
            sum(q4["table"][c]["adjust"] for c in CATEGORIES),
            sum(q2["table"][c]["cancel"] for c in CATEGORIES),
            sum(q4["table"][c]["cancel"] for c in CATEGORIES),
        ]
    )
    cmp_rows.append(
        ["归一化幅度", "-", "-", f"{q2['amplitude_normalised']:.1f}", f"{q4['amplitude_normalised']:.1f}", "-", "-"]
    )
    _write_table(
        ctx,
        "tab_q4_compare",
        ["类别", "保留(问2)", "保留(问4)", "调整(问2)", "调整(问4)", "撤销(问2)", "撤销(问4)"],
        cmp_rows,
    )
    try:
        variant = ctx.dep_data("resolve_interval", "variant_uncapped.json")
    except Exception:
        variant = None
    if variant:
        _write_table(
            ctx,
            "tab_q4_variant",
            ["模型", "动作数", "目标向量", "撤销合计", "调整合计", "最晚结束时刻/Δt", "用时/s", "独立校验"],
            [
                [
                    "主模型：e_i ≤ T_end（不增加时频资源）",
                    q4["model"]["vars"],
                    _vector_text(q4["vector"]),
                    sum(q4["vector"][0:3]),
                    sum(q4["vector"][3:6]),
                    q4["horizon_after"],
                    f"{q4['primary']['seconds']:.0f}",
                    "通过",
                ],
                [
                    "对照：不设时间范围上限",
                    variant["vars"],
                    _vector_text(variant["vector"]),
                    sum(variant["vector"][0:3]),
                    sum(variant["vector"][3:6]),
                    variant["horizon_after"],
                    f"{variant['seconds']:.0f}",
                    "通过" if variant["validator_ok"] else "未通过",
                ],
            ],
            align="lrlrrrrc",
        )
    _write_table(
        ctx,
        "tab_q4_adjustments",
        ["装备编号", "动作", "原频段", "新频段", "原首次时间", "新首次时间", "原间隔", "新间隔"],
        _adjustment_rows(plans, q4_dec, True),
        align="llllllrr",
        long=True,
    )
    scheme_rows4 = []
    for name in ("P", "T", "S", "W"):
        alt = q4_alt.get(name)
        if alt and alt["canonical_vector"]:
            v = alt["canonical_vector"]
            scheme_rows4.append(
                [
                    name,
                    f"{v[0]}/{v[1]}/{v[2]}",
                    f"{v[3]}/{v[4]}/{v[5]}",
                    sum(v[3:6]),
                    f"{v[6] / 10:.1f}",
                    alt["shifts"]["gap"]["count"],
                    f"{alt.get('budget_seconds', 0):.0f}",
                    f"{alt['seconds']:.1f}",
                    "通过" if alt["validator_ok"] else "未通过",
                ]
            )
    _write_table(
        ctx,
        "tab_q4_schemes",
        [
            "目标方案",
            "撤销 A/B/C",
            "调整 A/B/C",
            "调整合计",
            "归一化幅度",
            "间隔调整数",
            "预算/s",
            "用时/s",
            "独立校验",
        ],
        scheme_rows4,
        align="lrrrrrrrc",
    )
    _solver_tables(ctx, "q4", q4)
    _write_table(
        ctx,
        "tab_q4_cancelled",
        ["装备编号", "频段", "首次时间", "原冲突邻居数", "其中 A/B 类", "合法调整动作数", "其中在本方案下无冲突"],
        _cancelled_rows(
            plans,
            q4_dec,
            conflicts,
            Limits(
                fmax=int(q4["limits"]["fmax"]),
                tmax=int(q4["limits"]["tmax"]),
                gmax=int(q4["limits"]["gmax"]),
                gap_categories=tuple(q4["limits"]["gap_categories"]),
            ),
        ),
        align="lllrrrr",
    )

    val_rows = []
    for stage_name, label in (
        ("detect", "问题 1 冲突检测"),
        ("resolve", "问题 2 消解方案"),
        ("pack", "问题 3 新增计划"),
        ("resolve_interval", "问题 4 消解方案"),
    ):
        rep = ctx.dep_data(stage_name, "validation_report.json")
        if stage_name == "detect":
            detail = (
                f"真值 {rep.get('truth_pairs')} 对，报告 {rep.get('reported_pairs')} 对，"
                f"缺失 {len(rep.get('missing', []))}，多余 {len(rep.get('extra', []))}"
            )
        elif stage_name == "pack":
            detail = f"新增 {rep.get('n_new')}，剩余冲突 {rep.get('remaining_conflicts')}"
        else:
            detail = (
                f"{rep.get('n_decisions')} 个决策，存留 {rep.get('n_survivors')}，"
                f"剩余冲突 {rep.get('remaining_conflicts')}"
            )
        val_rows.append([label, rep.get("method", ""), detail, "通过" if rep.get("ok") else "未通过"])
    _write_table(ctx, "tab_validation", ["对象", "独立校验方法", "校验内容", "结论"], val_rows, align="lllc")

    tiny = ctx.dep_data("bench", "tiny.json")
    _write_table(
        ctx,
        "tab_bench_tiny",
        [
            "实例",
            "计划数",
            "频段数",
            "冲突对",
            "动作组合数",
            "穷举最优向量",
            "撤销分量",
            "CP-SAT 向量",
            "一致",
            "穷举用时/s",
        ],
        [
            [
                r["instance"],
                r["plans"],
                r.get("bands", "-"),
                r["conflicts"],
                r["combinations"],
                _vector_text(r["exhaustive_vector"]),
                r.get("cancellations", 0),
                _vector_text(r["cpsat_vector"]),
                "是" if r["agree"] else "否",
                f"{r['exhaustive_seconds']:.2f}",
            ]
            for r in tiny
        ],
        align="rrrrrlrlcr",
        long=True,
    )
    scaling = ctx.dep_data("bench", "scaling.json")
    _write_table(
        ctx,
        "tab_bench_scaling",
        [
            "n",
            "时间范围",
            "冲突对",
            "成对检测/s（中位数）",
            "扫描线/s（中位数）",
            "变量数",
            "约束数",
            "建模/s",
            "CP-SAT 状态",
            "求解/s",
            "撤销合计",
            "调整合计",
        ],
        [
            [
                r["n"],
                r["horizon"],
                r["conflicts"],
                f"{r['pairwise_seconds']:.2f}",
                f"{r['sweep_seconds']:.3f}",
                r["vars"],
                r["rows"],
                f"{r['build_seconds']:.1f}",
                r["cpsat_status"],
                f"{r['cpsat_seconds']:.1f}",
                sum(r["vector"][0:3]) if r["vector"] else "-",
                sum(r["vector"][3:6]) if r["vector"] else "-",
            ]
            for r in scaling
        ],
        align="rrrrrrrrlrrr",
    )
    cases = ctx.dep_data("sensitivity", "cases.json")
    _write_table(
        ctx,
        "tab_sensitivity",
        ["最大频段平移", "最大时间平移", "撤销 A/B/C", "调整 A/B/C", "调整合计", "归一化幅度", "各级最优", "用时/s"],
        [
            [
                r["fmax"],
                r["tmax"],
                f"{r['vector'][0]}/{r['vector'][1]}/{r['vector'][2]}",
                f"{r['vector'][3]}/{r['vector'][4]}/{r['vector'][5]}",
                r["adjust_total"],
                f"{r['amplitude']:.1f}",
                "是" if r["all_optimal"] else "否",
                f"{r['seconds']:.1f}",
            ]
            for r in cases
            if r["adjust_total"] is not None
        ],
        align="rrrrrrcr",
    )
    files = sorted(p.name for p in (ctx.stage_dir / "tables").glob("*.tex"))
    ctx.number("TableCount", len(files))
    return {"tables": files}
