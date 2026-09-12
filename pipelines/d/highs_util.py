"""HiGHS process-level settings shared by the resolution and packing models."""

from __future__ import annotations

_THREADS: list[int] = []


def highs_threads(requested: int) -> int:
    """Thread count to pass to HiGHS in this process.

    HiGHS initialises its global task executor on the first ``run()`` and a later solve that asks for a
    different ``threads`` value fails silently (model status "Not Set", objective 0). The first value used
    in the process is therefore kept for every subsequent solve."""
    if not _THREADS:
        _THREADS.append(max(1, int(requested)))
    return _THREADS[0]
