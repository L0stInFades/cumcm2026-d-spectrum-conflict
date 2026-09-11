from __future__ import annotations

from pathlib import Path

from forge.packaging import build_zip, code_members, run_members
from forge.tex import aux_page, summarize_log, tex_escape


def test_zip_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "b.py").write_text("print(2)")
    (src / "a.py").write_text("print(1)")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "a.pyc").write_bytes(b"x")
    members = code_members(src, ["**/*.py"])
    assert [m[0] for m in members] == ["a.py", "b.py"]
    one = build_zip(members, tmp_path / "one.zip")
    two = build_zip(list(reversed(members)), tmp_path / "two.zip")
    assert one["sha256"] == two["sha256"] and one["members"] == 2


def test_run_members_prefix(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    (run / "q1").mkdir(parents=True)
    (run / "q1" / "out.json").write_text("{}")
    assert run_members(run, ["q1", "missing"]) == [("runs/r1/q1/out.json", run / "q1" / "out.json")]


def test_log_summary_and_aux_page(tmp_path: Path) -> None:
    log = (
        "LaTeX Warning: Reference `fig:x' on page 3 undefined on input line 10.\n"
        "Overfull \\hbox (12.5pt too wide) in paragraph\n"
        "Missing character: There is no 龘 in font Latin Modern!\n"
        "! Undefined control sequence.\n"
        "Output written on main.pdf (7 pages).\n"
    )
    summary = summarize_log(log)
    assert summary["undefined_references"] == ["fig:x"]
    assert summary["overfull_max_pt"] == 12.5 and summary["missing_characters"] == 1
    assert summary["errors"] == ["Undefined control sequence."] and summary["pages_from_log"] == 7
    aux = tmp_path / "main.aux"
    aux.write_text("\\newlabel{page:body-end}{{}{27}{}{page:body-end}{}}\n\\newlabel{sec:a}{{2.1}{5}{}{}{}}\n")
    assert aux_page(aux, "page:body-end") == 27 and aux_page(aux, "sec:a") == 5 and aux_page(aux, "nope") is None


def test_tex_escape() -> None:
    assert tex_escape("a_b & 100% #1") == r"a\_b \& 100\% \#1"
