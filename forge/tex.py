"""XeLaTeX compilation and log analysis (only ever executed inside Modal)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

_UNDEF_REF = re.compile(r"LaTeX Warning: Reference `([^']+)' on page \d+ undefined")
_UNDEF_CIT = re.compile(r"LaTeX Warning: Citation `([^']+)' on page \d+ undefined")
_OVERFULL = re.compile(r"Overfull \\hbox \(([\d.]+)pt too wide\)")
_MISSING = re.compile(r"Missing character: There is no (.+?) in font")
_ERROR = re.compile(r"^! (.*)$", re.M)
_PAGES = re.compile(r"Output written on .*? \((\d+) pages?")


def tex_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("TEXMFVAR", "/tmp/texmf-var")
    env.setdefault("TEXMFCONFIG", "/tmp/texmf-config")
    env.setdefault("HOME", "/tmp")
    env["max_print_line"] = "2000"
    env["error_line"] = "254"
    env["half_error_line"] = "238"
    return env


def summarize_log(log: str) -> dict[str, Any]:
    overfull = [float(x) for x in _OVERFULL.findall(log)]
    missing = _MISSING.findall(log)
    pages = _PAGES.search(log)
    return {
        "undefined_references": sorted(set(_UNDEF_REF.findall(log))),
        "undefined_citations": sorted(set(_UNDEF_CIT.findall(log))),
        "overfull_count": len(overfull),
        "overfull_max_pt": max(overfull) if overfull else 0.0,
        "missing_characters": len(missing),
        "missing_character_samples": sorted(set(missing))[:10],
        "errors": _ERROR.findall(log)[:10],
        "pages_from_log": int(pages.group(1)) if pages else None,
    }


def aux_page(aux: Path, label: str) -> int | None:
    """Page number recorded for ``\\label{label}`` in the .aux file (hyperref-compatible)."""
    if not aux.exists():
        return None
    pattern = re.compile(r"\\newlabel\{" + re.escape(label) + r"\}\{\{[^{}]*\}\{(\d+)\}")
    match = pattern.search(aux.read_text(encoding="utf-8", errors="replace"))
    return int(match.group(1)) if match else None


def compile_tex(
    workdir: Path,
    main: str,
    jobname: str,
    *,
    passes: int = 3,
    bibtex: bool = True,
    timeout: int = 1200,
) -> dict[str, Any]:
    env = tex_env()
    runs: list[dict[str, Any]] = []
    log_path = workdir / f"{jobname}.log"

    def xelatex(tag: str) -> None:
        proc = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", f"-jobname={jobname}", main],
            cwd=workdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
        runs.append({"pass": tag, "rc": proc.returncode})
        if proc.returncode != 0:
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else proc.stdout
            errors = _ERROR.findall(log)
            raise RuntimeError(
                f"xelatex failed on pass {tag} for {main}: "
                + " | ".join(errors[:5])
                + "\n--- log tail ---\n"
                + log[-4000:]
            )

    xelatex("1")
    aux = workdir / f"{jobname}.aux"
    if bibtex and aux.exists():
        aux_text = aux.read_text(encoding="utf-8", errors="replace")
        if "\\citation" in aux_text and "\\bibdata" in aux_text:
            proc = subprocess.run(
                ["bibtex", jobname], cwd=workdir, capture_output=True, text=True, env=env, timeout=timeout, check=False
            )
            runs.append({"pass": "bibtex", "rc": proc.returncode, "tail": proc.stdout[-1500:]})
    for i in range(2, passes + 1):
        xelatex(str(i))
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    return {
        "pdf": workdir / f"{jobname}.pdf",
        "log": log_path,
        "aux": aux,
        "runs": runs,
        "summary": summarize_log(log_text),
    }


def tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def tex_path(path: str) -> str:
    """Typeset a file path so that it can break across lines (hyperref/xurl); falls back to \\texttt."""
    if any(ch in path for ch in "{}%#\\") or not path.isascii():
        return f"\\texttt{{{tex_escape(path)}}}"  # CJK names need the CJK mono font, not the url font
    return f"\\nolinkurl{{{path}}}"
