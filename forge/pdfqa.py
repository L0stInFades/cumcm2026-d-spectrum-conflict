"""PDF inspection for quality gates (PyMuPDF)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

A4_PT = (595.276, 841.89)


def inspect_pdf(path: Path, *, with_text: bool = True) -> dict[str, Any]:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    pages: list[dict[str, Any]] = []
    texts: list[str] = []
    fonts: dict[int, dict[str, Any]] = {}
    unembedded: list[str] = []
    for index, page in enumerate(doc, start=1):
        rect = page.rect
        pages.append(
            {
                "page": index,
                "width_pt": round(rect.width, 2),
                "height_pt": round(rect.height, 2),
                "a4": abs(rect.width - A4_PT[0]) < 3 and abs(rect.height - A4_PT[1]) < 3,
            }
        )
        if with_text:
            texts.append(page.get_text("text"))
        for font in page.get_fonts(full=True):
            xref, ftype, basefont = font[0], font[2], font[3]
            if xref in fonts:
                continue
            embedded = ftype == "Type3"
            if not embedded and xref:
                try:
                    embedded = len(doc.extract_font(xref)[3]) > 0
                except Exception:
                    embedded = False
            fonts[xref] = {"name": basefont, "type": ftype, "embedded": bool(embedded)}
            if not embedded:
                unembedded.append(basefont)
    return {
        "pages": len(doc),
        "page_boxes": pages,
        "all_a4": all(p["a4"] for p in pages),
        "fonts": list(fonts.values()),
        "unembedded_fonts": sorted(set(unembedded)),
        "texts": texts,
        "metadata": doc.metadata,
    }


def scan_strings(texts: Iterable[str], patterns: Iterable[str], *, context: int = 40) -> list[dict[str, Any]]:
    compiled = [(p, re.compile(p)) for p in patterns]
    hits: list[dict[str, Any]] = []
    for page_no, text in enumerate(texts, start=1):
        for raw, pattern in compiled:
            for match in pattern.finditer(text):
                start, end = max(0, match.start() - context), min(len(text), match.end() + context)
                hits.append({"page": page_no, "pattern": raw, "context": text[start:end].replace("\n", " ")})
    return hits
