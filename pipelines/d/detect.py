"""Conflict detection (Problem 1): pairwise two-pointer method and band-bucketed sweep line.

Two plans conflict when their band intervals overlap and at least one pair of uses overlaps in time
(half-open intervals, MDR-0001). ``detect_pairwise`` is the O(n^2 (m_i + m_j)) reference and
``detect_bandsweep`` the O(N log N + K) scalable method; both must return the same pair set.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from pipelines.d.plans import CATEGORIES, Plan


def intervals_overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    """Half-open intervals ``[a0,a1)`` and ``[b0,b1)`` intersect."""
    return a0 < b1 and b0 < a1


def freq_overlap(a: Plan, b: Plan) -> bool:
    return intervals_overlap(a.f, a.f_end, b.f, b.f_end)


def uses_overlap(a: Plan, b: Plan) -> bool:
    """True when some use of ``a`` overlaps some use of ``b`` in time (two-pointer merge over sorted uses)."""
    ua, ub = a.uses(), b.uses()
    i = j = 0
    while i < len(ua) and j < len(ub):
        s1, e1 = ua[i]
        s2, e2 = ub[j]
        if s1 < e2 and s2 < e1:
            return True
        if e1 <= e2:
            i += 1
        else:
            j += 1
    return False


def overlapping_uses(a: Plan, b: Plan) -> list[tuple[int, int]]:
    """All (k, l) use pairs of ``a`` and ``b`` that overlap in time (full O(m_a m_b) enumeration)."""
    return [
        (k, l)
        for k, (s1, e1) in enumerate(a.uses())
        for l, (s2, e2) in enumerate(b.uses())
        if intervals_overlap(s1, e1, s2, e2)
    ]


def plans_conflict(a: Plan, b: Plan) -> bool:
    return freq_overlap(a, b) and uses_overlap(a, b)


def detect_pairwise(plans: list[Plan]) -> list[tuple[int, int]]:
    """Reference detector: every pair, band test first, then two-pointer time test. Returns sorted index pairs."""
    out: list[tuple[int, int]] = []
    n = len(plans)
    for i in range(n):
        a = plans[i]
        for j in range(i + 1, n):
            b = plans[j]
            if freq_overlap(a, b) and uses_overlap(a, b):
                out.append((i, j))
    return out


def detect_bandsweep(plans: list[Plan]) -> list[tuple[int, int]]:
    """Sweep line per band: bucket every use of every plan into the bands it occupies, sort by start,
    and report pairs whose uses overlap. Complexity O(N log N + K) with N = total (use, band) items."""
    buckets: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for idx, p in enumerate(plans):
        for start, end in p.uses():
            for band in range(p.f, p.f_end):
                buckets[band].append((start, end, idx))
    found: set[tuple[int, int]] = set()
    for items in buckets.values():
        items.sort()
        active: list[tuple[int, int]] = []  # (end, idx), pruned lazily
        for start, end, idx in items:
            active = [(e, k) for e, k in active if e > start]
            for _, k in active:
                found.add((k, idx) if k < idx else (idx, k))
            active.append((end, idx))
    return sorted(found)


def pair_key(a: str, b: str) -> str:
    return "".join(sorted((a, b)))


def conflict_records(plans: list[Plan], pairs: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Per conflict pair: ids, categories and the number of overlapping use pairs."""
    records = []
    for i, j in pairs:
        a, b = plans[i], plans[j]
        uses = overlapping_uses(a, b)
        records.append(
            {
                "id1": a.pid,
                "id2": b.pid,
                "pair": pair_key(a.cat, b.cat),
                "use_pairs": len(uses),
                "first_overlap_time": min(max(a.uses()[k][0], b.uses()[l][0]) for k, l in uses),
                "band_overlap": min(a.f_end, b.f_end) - max(a.f, b.f),
            }
        )
    return records


def graph_stats(plans: list[Plan], pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """Conflict-graph statistics: category-pair counts, degrees, components, involvement."""
    import networkx as nx

    graph = nx.Graph()
    graph.add_nodes_from(range(len(plans)))
    graph.add_edges_from(pairs)
    degrees = dict(graph.degree())
    by_pair: Counter[str] = Counter(pair_key(plans[i].cat, plans[j].cat) for i, j in pairs)
    involved = {c: sum(1 for i, p in enumerate(plans) if p.cat == c and degrees[i] > 0) for c in CATEGORIES}
    counts = {c: sum(1 for p in plans if p.cat == c) for c in CATEGORIES}
    components = sorted((len(c) for c in nx.connected_components(graph) if len(c) > 1), reverse=True)
    degree_hist: Counter[int] = Counter(degrees.values())
    return {
        "pairs": len(pairs),
        "by_pair": {k: int(by_pair.get(k, 0)) for k in ("AA", "AB", "AC", "BB", "BC", "CC")},
        "plans_involved": int(sum(involved.values())),
        "plans_involved_by_cat": involved,
        "plans_by_cat": counts,
        "max_degree": int(max(degrees.values(), default=0)),
        "mean_degree": float(sum(degrees.values()) / max(len(plans), 1)),
        "degree_hist": {str(k): int(v) for k, v in sorted(degree_hist.items())},
        "components": len(components),
        "largest_component": int(components[0]) if components else 0,
        "component_sizes": components,
        "density": float(len(pairs) / max(len(plans) * (len(plans) - 1) / 2, 1)),
        "top_degree": sorted(
            ({"pid": plans[i].pid, "degree": degrees[i]} for i in range(len(plans))),
            key=lambda r: (-int(r["degree"]), str(r["pid"])),
        )[:10],
    }
