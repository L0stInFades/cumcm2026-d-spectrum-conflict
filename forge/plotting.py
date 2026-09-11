"""House style for paper figures: vector PDF output, CJK-capable fonts, accessible palette."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

OKABE_ITO = ["#0072B2", "#D55E00", "#009E73", "#E69F00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
_CJK_CANDIDATES = (
    ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("Droid Sans Fallback", "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
)
_STATE: dict[str, Any] = {}


class _Catcher(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def cjk_font_family() -> str:
    """Pick a CJK font that renders into PDF without missing glyphs (cached per process)."""
    if "family" in _STATE:
        return str(_STATE["family"])
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager
    from matplotlib import pyplot as plt

    chosen = "DejaVu Sans"
    for family, path in _CJK_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            font_manager.fontManager.addfont(path)
        except Exception:  # noqa: BLE001
            continue
        catcher = _Catcher()
        for name in ("matplotlib.font_manager", "matplotlib.backends.backend_pdf", "matplotlib"):
            logging.getLogger(name).addHandler(catcher)
        try:
            fig, ax = plt.subplots(figsize=(2, 1))
            ax.text(0.1, 0.5, "温度 水分 药材 频段 关键词", fontfamily=family)
            probe = Path("/tmp") / f"forge_font_probe_{family.replace(' ', '_')}.pdf"
            fig.savefig(probe, format="pdf")
            plt.close(fig)
            bad = [m for m in catcher.records if "missing" in m.lower() or "glyph" in m.lower() or "not found" in m.lower()]
            if not bad:
                chosen = family
                break
        except Exception:  # noqa: BLE001
            continue
        finally:
            for name in ("matplotlib.font_manager", "matplotlib.backends.backend_pdf", "matplotlib"):
                logging.getLogger(name).removeHandler(catcher)
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
