"""House style for paper figures: vector PDF output, CJK-capable fonts, accessible palette."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

OKABE_ITO = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
# (family name as matplotlib registers it, font file). TTC files expose only their first face,
# which is why the Noto CJK collection is addressed by its JP face name.
_CJK_CANDIDATES = (
    ("WenQuanYi Micro Hei", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
    ("Noto Sans CJK JP", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("Droid Sans Fallback", "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
)
_PROBE_TEXT = "温度 T 水分 C 药材 频段 关键词 abc 0.25"
_STATE: dict[str, Any] = {}


class _Catcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def _probe(family: str) -> bool:
    """True when ``family`` (with DejaVu Sans as Latin fallback) renders the probe text into PDF cleanly."""
    from matplotlib import pyplot as plt

    catcher = _Catcher()
    loggers = [logging.getLogger(n) for n in ("matplotlib.font_manager", "matplotlib.backends.backend_pdf", "matplotlib")]
    for lg in loggers:
        lg.addHandler(catcher)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            fig, ax = plt.subplots(figsize=(2.5, 1))
            ax.text(0.05, 0.5, _PROBE_TEXT, fontfamily=[family, "DejaVu Sans"])
            ax.set_axis_off()
            probe = Path("/tmp") / f"forge_font_probe_{family.replace(' ', '_')}.pdf"
            fig.savefig(probe, format="pdf")
            plt.close(fig)
        messages = [str(w.message) for w in caught] + catcher.records
        bad = [m for m in messages if "missing from font" in m or "not found" in m.lower()]
        return not bad
    except Exception:  # noqa: BLE001
        return False
    finally:
        for lg in loggers:
            lg.removeHandler(catcher)


def cjk_font_family() -> str:
    """Pick a CJK font that renders into PDF without missing glyphs (cached per process)."""
    if "family" in _STATE:
        return str(_STATE["family"])
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager

    chosen = "DejaVu Sans"
    for family, path in _CJK_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            font_manager.fontManager.addfont(path)
        except Exception:  # noqa: BLE001
            continue
        if _probe(family):
            chosen = family
            break
    _STATE["family"] = chosen
    return chosen


def setup(font_size: float = 9.0) -> str:
    import matplotlib

    matplotlib.use("Agg")
    from cycler import cycler
    from matplotlib import pyplot as plt

    family = cjk_font_family()
    plt.rcParams.update({
        "font.family": [family, "DejaVu Sans"],
        "font.size": font_size,
        "axes.titlesize": font_size + 1,
        "axes.labelsize": font_size,
        "legend.fontsize": font_size - 1,
        "xtick.labelsize": font_size - 1,
        "ytick.labelsize": font_size - 1,
        "axes.prop_cycle": cycler(color=OKABE_ITO),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "lines.linewidth": 1.4,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.unicode_minus": False,
        "figure.constrained_layout.use": True,
    })
    return family


def new_figure(width_in: float = 6.3, height_in: float = 3.4, **kwargs: Any) -> tuple[Any, Any]:
    from matplotlib import pyplot as plt

    setup()
    return plt.subplots(figsize=(width_in, height_in), **kwargs)


def save(fig: Any, pdf_path: Path, *, png_preview: bool = True, dpi: int = 200) -> dict[str, Any]:
    from matplotlib import pyplot as plt

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(pdf_path, format="pdf")
    out = {"pdf": str(pdf_path), "bytes": pdf_path.stat().st_size}
    if png_preview:
        png = pdf_path.with_suffix(".png")
        fig.savefig(png, format="png", dpi=dpi)
        out["png"] = str(png)
    plt.close(fig)
    return out
