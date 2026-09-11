"""Problem-agnostic stages: ingest, lint, test, paper, qa, package, release."""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge import packaging, pdfqa, xlsx
from forge.context import StageContext
from forge.hashing import hash_tree, sha256_file
from forge.runner import stage
from forge.tex import aux_page, compile_tex, tex_escape, tex_path

PLANNED_STAGE_FILES = {
    "lint": ["ruff_check.txt", "ruff_format.txt", "mypy.txt", "lint_report.json", "manifest.json", "events.jsonl"],
    "test": ["junit.xml", "coverage.json", "pytest.txt", "test_report.json", "manifest.json", "events.jsonl"],
    "qa": ["qa_report.json", "manifest.json", "events.jsonl"],
}
MEMBER_DESCRIPTIONS = (
    (r"^forge/", "云端运行时（阶段执行、清单、契约、排版、打包）"),
    (r"^pipelines/common/", "通用阶段：数据接入、门禁、论文、质量检查、打包发布"),
    (r"^pipelines/", "本题建模与求解程序"),
    (r"^tools/", "本地控制面：提交云端任务、下载、校验散列"),
    (r"^tests/", "单元 / 性质 / 集成测试"),
    (r"^configs/", "运行配置与项目元数据"),
    (r"^manuscript/", "论文 LaTeX 源码"),
    (r"^docs/", "工程规范、建模标准、决策记录"),
    (r"/ingest/", "原始数据接入结果（散列、题目文本、规范化数据）"),
    (r"/validate/", "数据契约校验报告与数据画像"),
    (r"/results/", "结果工作簿与求解输出"),
    (r"/figures/", "论文图（矢量 PDF 与预览 PNG）"),
    (r"/tables/", "论文表（LaTeX 片段与 CSV）"),
    (r"/lint/", "静态检查报告"),
    (r"/test/", "测试报告与覆盖率"),
    (r"/qa/", "论文与结果文件质量门禁报告"),
    (r"manifest\.json$", "阶段清单（输入输出散列、环境、参数）"),
    (r"events\.jsonl$", "结构化运行日志"),
    (r"^AI工具使用详情\.pdf$", "AI 工具使用详情"),
    (r"^AI_USAGE\.md$", "AI 工具使用记录（源文件）"),
    (r"^Makefile$", "本地快捷命令（只提交云端任务）"),
    (r"^pyproject\.toml$", "项目元数据与静态检查配置"),
    (r"^README\.md$", "仓库说明与复现入口"),
    (r"^CHANGELOG\.md$", "变更记录"),
    (r"^UNLICENSE$", "公有领域声明（Unlicense）"),
    (r"^REPRODUCE\.md$", "复现说明"),
    (r"^MANIFEST\.json$", "支撑材料成员清单与 SHA-256"),
)


def _describe(name: str) -> str:
    for pattern, text in MEMBER_DESCRIPTIONS:
        if re.search(pattern, name):
            return text
    return ""


def _to_parquet(df: Any, target: Path) -> None:
    frame = df.copy()
    frame.columns = [str(c).strip() for c in frame.columns]
    try:
        frame.to_parquet(target, index=False)
    except Exception:
        for col in frame.columns:
            if frame[col].dtype == object:
                frame[col] = frame[col].map(
                    lambda v: None if v is None or (isinstance(v, float) and v != v) else str(v)
                )
        frame.to_parquet(target, index=False)


@stage("ingest", description="Hash raw inputs, extract the problem text, convert every attachment sheet to parquet")
def ingest(ctx: StageContext) -> dict[str, Any]:
    import fitz

    document = fitz.open(ctx.problem_pdf)
    text = "\n\n".join(page.get_text("text", sort=True) for page in document)
    ctx.out("problem_text.txt").write_text(text, encoding="utf-8")
    inventory: dict[str, Any] = {
        "problem_pdf": {
            "path": ctx.project["problem_pdf"],
            "sha256": sha256_file(ctx.problem_pdf),
            "pages": len(document),
        },
        "files": [],
    }
    for path in sorted(ctx.attachments.rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        rel = path.relative_to(ctx.attachments).as_posix()
        is_template = path.parent == ctx.templates or ctx.templates in path.parents
        entry: dict[str, Any] = {
            "path": rel,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "template": is_template,
            "sheets": [],
        }
        for name, df in xlsx.read_sheets(path).items():
            sheet: dict[str, Any] = {"name": name, "rows": len(df), "columns": [str(c) for c in df.columns]}
            if not is_template:
                safe = re.sub(r"[^\w.-]+", "_", f"{path.stem}__{name}")
                target = ctx.out("data", f"{safe}.parquet")
                _to_parquet(df, target)
                sheet["parquet"] = target.relative_to(ctx.stage_dir).as_posix()
                sheet["dtypes"] = {str(c): str(t) for c, t in df.dtypes.items()}
                sheet["head"] = df.head(5).astype(str).values.tolist()
            entry["sheets"].append(sheet)
        inventory["files"].append(entry)
        ctx.log.info("ingest.file", path=rel, template=is_template, sheets=[s["name"] for s in entry["sheets"]])
    ctx.write_json("inventory.json", inventory)
    return {"files": len(inventory["files"]), "problem_chars": len(text)}


@stage("lint", description="Static gates: ruff check, ruff format --check, mypy")
def lint(ctx: StageContext) -> dict[str, Any]:
    returncodes: dict[str, int] = {}

    def run(name: str, cmd: list[str]) -> None:
        proc = subprocess.run(cmd, cwd=str(ctx.repo), capture_output=True, text=True, check=False)
        ctx.out(f"{name}.txt").write_text(proc.stdout + ("\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
        returncodes[name] = proc.returncode
        ctx.log.info("lint.tool", tool=name, rc=proc.returncode, tail=(proc.stdout + proc.stderr)[-400:])

    run("ruff_check", ["ruff", "check", "--no-cache", "--output-format", "concise", "."])
    run("ruff_format", ["ruff", "format", "--check", "--no-cache", "."])
    run("mypy", ["mypy", "--cache-dir", "/tmp/mypy", *ctx.cfg("gates.mypy_paths", ["forge"])])
    required = list(ctx.cfg("gates.lint_required", ["ruff_check", "ruff_format", "mypy"]))
    passed = all(returncodes.get(name, 1) == 0 for name in required)
    ctx.write_json("lint_report.json", {"passed": passed, "required": required, "returncodes": returncodes})
    if not passed:
        raise RuntimeError(f"lint gate failed: {returncodes}")
    return {"passed": passed, **returncodes}


@stage("test", description="pytest (unit, property, integration) with JUnit and coverage reports")
def test(ctx: StageContext) -> dict[str, Any]:
    env = {
        **os.environ,
        "COVERAGE_FILE": "/tmp/.coverage",
        "HYPOTHESIS_STORAGE_DIRECTORY": "/tmp/hypothesis",
        "FORGE_RUN_DIR": str(ctx.run_dir),
    }
    cmd = [
        "python",
        "-m",
        "pytest",
        "tests",
        "-q",
        "-p",
        "no:cacheprovider",
        "--rootdir",
        str(ctx.repo),
        f"--junitxml={ctx.out('junit.xml')}",
        "--cov=forge",
        "--cov=pipelines",
        f"--cov-report=json:{ctx.out('coverage.json')}",
        "--cov-report=term",
    ]
    extra = ctx.param("pytest_args")
    if extra:
        cmd += shlex.split(str(extra))
    proc = subprocess.run(cmd, cwd=str(ctx.repo), capture_output=True, text=True, env=env, check=False)
    ctx.out("pytest.txt").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    print(proc.stdout[-5000:], flush=True)
    summary: dict[str, Any] = {"returncode": proc.returncode}
    junit = ctx.stage_dir / "junit.xml"
    if junit.exists():
        root = ET.parse(junit).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is not None:
            summary.update({k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")})
    coverage = ctx.stage_dir / "coverage.json"
    if coverage.exists():
        summary["coverage_percent"] = round(json.loads(coverage.read_text())["totals"]["percent_covered"], 2)
    ctx.write_json("test_report.json", summary)
    if proc.returncode != 0:
        raise RuntimeError(f"tests failed: {summary}\n{proc.stdout[-2500:]}")
    return summary


def _support_members(ctx: StageContext, *, planned: bool) -> list[tuple[str, Path]]:
    members = packaging.code_members(ctx.repo, ctx.cfg("package.code_globs", []))
    for name in ctx.cfg("package.stages", []):
        directory = ctx.run_dir / name
        if (directory / "manifest.json").exists():
            members += packaging.run_members(ctx.run_dir, [name])
        elif planned and name in PLANNED_STAGE_FILES:
            members += [(f"runs/{ctx.run_id}/{name}/{f}", directory / f) for f in PLANNED_STAGE_FILES[name]]
    members.append(("AI工具使用详情.pdf", ctx.run_dir / "paper" / "AI工具使用详情.pdf"))
    members.append(("REPRODUCE.md", ctx.run_dir / "package" / "REPRODUCE.md"))
    members.append(("MANIFEST.json", ctx.run_dir / "package" / "MANIFEST.json"))
    return sorted(dict(members).items())


def _load_numbers(run_dir: Path) -> tuple[dict[str, str], list[str]]:
    numbers: dict[str, str] = {}
    conflicts: list[str] = []
    for path in sorted(run_dir.glob("*/numbers.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            if key in numbers and numbers[key] != value:
                conflicts.append(f"{key}: {numbers[key]!r} vs {value!r} ({path.parent.name})")
            numbers[key] = value
    return numbers, conflicts


def _stage_rows(ctx: StageContext) -> list[dict[str, Any]]:
    rows = []
    for manifest in sorted(ctx.run_dir.glob("*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        rows.append(
            {
                "stage": data["stage"],
                "status": data["status"],
                "duration_s": data.get("duration_s"),
                "outputs_digest": data.get("outputs_digest", ""),
                "modal_task_id": data.get("runtime", {}).get("modal_task_id"),
            }
        )
    return rows


@stage(
    "paper",
    description="Assemble generated inputs (numbers, tables, figures, code, support list) and compile with XeLaTeX",
)
def paper(ctx: StageContext) -> dict[str, Any]:
    sources = list(ctx.cfg("paper.sources", []))
    for source in sources:
        ctx.dep(source)
    build = Path("/tmp/build")
    shutil.rmtree(build, ignore_errors=True)
    shutil.copytree(
        ctx.repo / "manuscript", build, ignore=shutil.ignore_patterns("generated", "*.aux", "*.log", "*.pdf")
    )
    generated = build / "generated"
    (generated / "tables").mkdir(parents=True, exist_ok=True)
    (build / "figures").mkdir(exist_ok=True)

    numbers, conflicts = _load_numbers(ctx.run_dir)
    for conflict in conflicts:
        ctx.log.warn("paper.number_conflict", detail=conflict)
    lines = ["% generated by forge — do not edit"] + [
        f"\\newcommand{{\\val{key}}}{{{tex_escape(value)}}}" for key, value in sorted(numbers.items())
    ]
    (generated / "numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    n_tables = n_figures = 0
    for source in sources:
        directory = ctx.run_dir / source
        for table in sorted((directory / "tables").glob("*.tex")) if (directory / "tables").is_dir() else []:
            shutil.copy2(table, generated / "tables" / table.name)
            n_tables += 1
        for figure in sorted((directory / "figures").glob("*")) if (directory / "figures").is_dir() else []:
            if figure.suffix.lower() in {".pdf", ".png"}:
                shutil.copy2(figure, build / "figures" / figure.name)
                n_figures += 1

    code_ref = ctx.params.get("code_ref") or {}
    meta = [
        f"\\newcommand{{\\RunId}}{{{tex_escape(ctx.run_id)}}}",
        f"\\newcommand{{\\CodeSha}}{{{tex_escape(str(code_ref.get('git_sha', '')))}}}",
        f"\\newcommand{{\\BuildDate}}{{{datetime.now(UTC).strftime('%Y-%m-%d')}}}",
    ]
    (generated / "meta.tex").write_text("\n".join(meta) + "\n", encoding="utf-8")

    files = packaging.code_members(ctx.repo, ctx.cfg("paper.code_globs", []))
    listing = ["% generated by forge — complete source listing"]
    for rel, src in files:
        target = build / "code" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        language = {".py": "Python", ".tex": "[LaTeX]TeX"}.get(src.suffix, "{}")
        listing.append(f"\\needspace{{6\\baselineskip}}\\subsection*{{{tex_path(rel)}}}")
        listing.append(f"\\lstinputlisting[language={language}]{{code/{rel}}}")
    (generated / "code_listing.tex").write_text("\n".join(listing) + "\n", encoding="utf-8")

    members = _support_members(ctx, planned=True)
    rows = [
        "% generated by forge — support material file list",
        "\\begin{longtable}{@{}p{0.64\\linewidth}p{0.32\\linewidth}@{}}",
        "\\toprule 文件 & 说明 \\\\ \\midrule \\endhead \\bottomrule \\endfoot",
    ]
    rows += [f"{tex_path(name)} & {tex_escape(_describe(name))} \\\\" for name, _ in members]
    rows.append("\\end{longtable}")
    (generated / "support_files.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")
    ctx.write_json("support_members.json", [name for name, _ in members])

    stage_rows = _stage_rows(ctx)
    repro = [
        "% generated by forge — reproducibility record",
        "\\begin{longtable}{@{}llrl@{}}",
        "\\toprule 阶段 & 状态 & 用时/s & 输出摘要 (SHA-256 前 12 位) \\\\ \\midrule \\endhead \\bottomrule \\endfoot",
    ]
    repro += [
        f"\\texttt{{{tex_escape(r['stage'])}}} & {r['status']} & {r['duration_s'] or 0:.1f} & "
        f"\\texttt{{{r['outputs_digest'][:12]}}} \\\\"
        for r in stage_rows
    ]
    repro.append("\\end{longtable}")
    (generated / "repro_table.tex").write_text("\n".join(repro) + "\n", encoding="utf-8")

    result = compile_tex(build, str(ctx.cfg("paper.main", "main.tex")), "main", passes=3, bibtex=True)
    shutil.copy2(result["pdf"], ctx.out("main.pdf"))
    shutil.copy2(result["log"], ctx.out("main.log"))
    if result["aux"].exists():
        shutil.copy2(result["aux"], ctx.out("main.aux"))
    body_end = aux_page(result["aux"], "page:body-end")
    abstract_end = aux_page(result["aux"], "page:abstract-end")
    ai_summary = None
    if (build / "ai_usage.tex").exists():
        ai = compile_tex(build, "ai_usage.tex", "ai_usage", passes=2, bibtex=False)
        shutil.copy2(ai["pdf"], ctx.out("AI工具使用详情.pdf"))
        ai_summary = ai["summary"]
    info = pdfqa.inspect_pdf(ctx.out("main.pdf"), with_text=False)
    body_pages = (body_end - abstract_end) if body_end and abstract_end else None
    report = {
        "pages": info["pages"],
        "all_a4": info["all_a4"],
        "abstract_end_page": abstract_end,
        "body_end_page": body_end,
        "body_pages": body_pages,
        "log": result["summary"],
        "unembedded_fonts": info["unembedded_fonts"],
        "fonts": info["fonts"],
        "numbers": len(numbers),
        "number_conflicts": conflicts,
        "tables": n_tables,
        "figures": n_figures,
        "code_files": len(files),
        "support_members": len(members),
        "ai_usage_log": ai_summary,
        "stages": stage_rows,
    }
    ctx.write_json("paper_report.json", report)
    summary = result["summary"]
    return {
        "pages": info["pages"],
        "body_pages": body_pages,
        "undefined_refs": len(summary["undefined_references"]) + len(summary["undefined_citations"]),
        "overfull_max_pt": summary["overfull_max_pt"],
        "missing_chars": summary["missing_characters"],
        "figures": n_figures,
        "tables": n_tables,
    }


@stage("qa", deps=("paper",), description="Quality gates over the compiled paper and the result workbooks")
def qa(ctx: StageContext) -> dict[str, Any]:
    for required in ctx.cfg("qa.required_stages", ["lint", "test"]):
        ctx.dep(required)
    paper_dir = ctx.dep("paper")
    report = json.loads((paper_dir / "paper_report.json").read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        ctx.log.info("qa.check", name=name, ok=bool(ok), detail=detail)

    max_body = int(ctx.cfg("paper.max_body_pages", 30))
    check("abstract_single_page", report["abstract_end_page"] == 1, report["abstract_end_page"])
    check(
        "body_pages_within_limit",
        report["body_pages"] is not None and report["body_pages"] <= max_body,
        f"{report['body_pages']} <= {max_body}",
    )
    log = report["log"]
    check(
        "no_undefined_references",
        not log["undefined_references"] and not log["undefined_citations"],
        {"refs": log["undefined_references"][:10], "cites": log["undefined_citations"][:10]},
    )
    check("no_tex_errors", not log["errors"], log["errors"][:5])
    check("fonts_embedded", not report["unembedded_fonts"], report["unembedded_fonts"])
    check("a4_pages", report["all_a4"])
    check(
        "overfull_within_limit",
        log["overfull_max_pt"] <= float(ctx.cfg("paper.max_overfull_pt", 20.0)),
        f"max {log['overfull_max_pt']} pt, count {log['overfull_count']}",
    )
    check("no_missing_characters", log["missing_characters"] == 0, log["missing_character_samples"])
    check("no_number_conflicts", not report["number_conflicts"], report["number_conflicts"][:5])
    check("ai_usage_pdf_present", (paper_dir / "AI工具使用详情.pdf").exists())

    info = pdfqa.inspect_pdf(paper_dir / "main.pdf", with_text=True)
    deny_hits = pdfqa.scan_strings(info["texts"], ctx.cfg("qa.identity_denylist", []))
    watch_hits = pdfqa.scan_strings(info["texts"], ctx.cfg("qa.identity_watchlist", []))
    check("identity_denylist_clean", not deny_hits, deny_hits[:5])
    check("paper_size_under_20mb", (paper_dir / "main.pdf").stat().st_size <= 20 * 1024 * 1024)

    results_reports: list[dict[str, Any]] = []
    results_stage = str(ctx.cfg("qa.results_stage", "results"))
    require_results = bool(ctx.param("require_results", ctx.cfg("qa.require_results", True)))
    if ctx.has_stage(results_stage):
        contracts = importlib.import_module(f"pipelines.{ctx.project['package']}.contracts")
        results_dir = ctx.run_dir / results_stage
        for contract in contracts.RESULT_CONTRACTS:
            rep = xlsx.check_workbook(results_dir / contract.file, contract, ctx.templates / contract.template)
            results_reports.append(rep)
            check(f"result:{contract.file}", rep["ok"], rep["errors"][:5])
    else:
        check("results_stage_present", not require_results, f"stage '{results_stage}' not completed in this run")

    passed = all(c["ok"] for c in checks)
    ctx.write_json(
        "qa_report.json",
        {
            "passed": passed,
            "checks": checks,
            "identity_watchlist_hits": watch_hits,
            "results": results_reports,
            "paper": {k: v for k, v in report.items() if k != "fonts"},
        },
    )
    if not passed:
        raise RuntimeError("QA gate failed: " + ", ".join(c["name"] for c in checks if not c["ok"]))
    return {"passed": passed, "checks": len(checks), "watchlist_hits": len(watch_hits)}


def _reproduce_md(ctx: StageContext) -> str:
    rows = _stage_rows(ctx)
    code_ref = ctx.params.get("code_ref") or {}
    manifest = json.loads((ctx.run_dir / "ingest" / "manifest.json").read_text(encoding="utf-8"))
    packages = manifest.get("runtime", {}).get("packages", {})
    lines = [
        f"# 复现说明（run `{ctx.run_id}`）",
        "",
        "本目录内所有结果均由 Modal 云端按下列阶段生成；本地只提交任务、下载和核对 SHA-256。",
        "",
        f"- 代码版本：git `{code_ref.get('git_sha', '')}`（分支 `{code_ref.get('branch', '')}`）",
        f"- 运行环境：Python {manifest.get('runtime', {}).get('python', '')}，"
        f"{manifest.get('runtime', {}).get('platform', '')}",
        "- 依赖版本：" + ", ".join(f"{k}=={v}" for k, v in sorted(packages.items())),
        "",
        "## 阶段",
        "",
        "| 阶段 | 状态 | 用时 (s) | 输出摘要 | Modal 任务 |",
        "|---|---|---:|---|---|",
    ]
    lines += [
        f"| {r['stage']} | {r['status']} | {r['duration_s'] or 0:.1f} | `{r['outputs_digest'][:16]}` | "
        f"`{r['modal_task_id'] or ''}` |"
        for r in rows
    ]
    lines += [
        "",
        "## 复现命令",
        "",
        "```bash",
        "python3 tools/cli.py provision",
        "python3 tools/cli.py run ingest,validate --new-run",
        "python3 tools/cli.py run <科学阶段...> --size medium",
        "python3 tools/cli.py run lint,test,paper,qa,package,release",
        "python3 tools/cli.py release --version <tag>",
        "```",
        "",
        "每个阶段目录下的 `manifest.json` 记录输入、输出散列、参数与环境；`events.jsonl` 为结构化日志。",
        "",
    ]
    return "\n".join(lines)


@stage("package", deps=("qa",), description="Build the deterministic support-materials zip and its member manifest")
def package(ctx: StageContext) -> dict[str, Any]:
    planned = set(json.loads((ctx.dep("paper") / "support_members.json").read_text(encoding="utf-8")))
    ctx.out("REPRODUCE.md").write_text(_reproduce_md(ctx), encoding="utf-8")
    members = [(name, path) for name, path in _support_members(ctx, planned=False) if name != "MANIFEST.json"]
    missing = [name for name, path in members if not path.exists()]
    if missing:
        raise RuntimeError(f"support members missing on disk: {missing[:10]}")
    actual = {name for name, _ in members} | {"MANIFEST.json"}
    drift = sorted(actual ^ planned)
    if drift and not ctx.param("allow_member_drift"):
        raise RuntimeError(f"support material members differ from the list printed in the paper: {drift[:20]}")
    manifest = {
        "run_id": ctx.run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "members": [
            {"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size} for name, path in members
        ],
    }
    manifest_path = ctx.out("MANIFEST.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    members.append(("MANIFEST.json", manifest_path))
    zip_info = packaging.build_zip(members, ctx.out("支撑材料.zip"), comment=f"forge run {ctx.run_id}")
    limit = int(ctx.cfg("package.max_bytes", 20 * 1024 * 1024))
    ctx.write_json("package_report.json", {**zip_info, "limit_bytes": limit, "drift": drift})
    if zip_info["bytes"] > limit:
        raise RuntimeError(f"support zip {zip_info['bytes']} bytes exceeds limit {limit}")
    return {"members": zip_info["members"], "bytes": zip_info["bytes"], "drift": len(drift)}


@stage(
    "release",
    deps=("package",),
    description="Assemble deliverables (paper, result workbooks, support zip) with SHA-256 manifest",
)
def release(ctx: StageContext) -> dict[str, Any]:
    qa_report = json.loads((ctx.dep("qa") / "qa_report.json").read_text(encoding="utf-8"))
    if not qa_report["passed"] and not ctx.param("allow_failed_qa"):
        raise RuntimeError("release refused: QA gate did not pass")
    paper_dir = ctx.dep("paper")
    files: dict[str, Path] = {str(ctx.cfg("release.paper_name", "论文.pdf")): paper_dir / "main.pdf"}
    results_stage = str(ctx.cfg("qa.results_stage", "results"))
    if ctx.has_stage(results_stage):
        for name in ctx.project.get("result_files", []):
            files[name] = ctx.run_dir / results_stage / name
    elif not ctx.param("allow_missing_results"):
        raise RuntimeError("release refused: results stage missing")
    files["支撑材料.zip"] = ctx.dep("package") / "支撑材料.zip"
    files["AI工具使用详情.pdf"] = paper_dir / "AI工具使用详情.pdf"
    manifest: dict[str, Any] = {
        "run_id": ctx.run_id,
        "code_ref": ctx.params.get("code_ref"),
        "files": {},
        "qa_passed": qa_report["passed"],
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    for name, source in files.items():
        if not source.exists():
            raise RuntimeError(f"release file missing: {name} ({source})")
        target = ctx.out(name)
        shutil.copy2(source, target)
        manifest["files"][name] = {"sha256": sha256_file(target), "bytes": target.stat().st_size}
    notes = [
        f"# 发布说明 — run {ctx.run_id}",
        "",
        f"- 代码：`{(ctx.params.get('code_ref') or {}).get('git_sha', '')}`",
        f"- QA：{'通过' if qa_report['passed'] else '未通过（强制发布）'}",
        "",
        "| 文件 | 字节 | SHA-256 |",
        "|---|---:|---|",
    ]
    notes += [f"| {n} | {m['bytes']} | `{m['sha256']}` |" for n, m in manifest["files"].items()]
    ctx.out("RELEASE_NOTES.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    ctx.write_json("release_manifest.json", manifest)
    return {
        "files": len(files),
        "paper_bytes": manifest["files"][str(ctx.cfg("release.paper_name", "论文.pdf"))]["bytes"],
    }


FMT_IGNORE = (".git", "artifacts", "releases", "__pycache__", ".forge", ".DS_Store", ".mypy_cache", ".ruff_cache")


@stage("fmt", description="ruff --fix and ruff format in the cloud; changed files are exported for a local copy-back")
def fmt(ctx: StageContext) -> dict[str, Any]:
    work = Path("/tmp/fmt")
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(ctx.repo, work, ignore=shutil.ignore_patterns(*FMT_IGNORE, "*.pyc"))
    before = hash_tree(work, ignore=FMT_IGNORE)
    fix = subprocess.run(
        ["ruff", "check", "--fix", "--no-cache", "--output-format", "concise", "."],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )
    form = subprocess.run(["ruff", "format", "--no-cache", "."], cwd=work, capture_output=True, text=True, check=False)
    after = hash_tree(work, ignore=FMT_IGNORE)
    changed = sorted(rel for rel in after if rel not in before or after[rel]["sha256"] != before[rel]["sha256"])
    for rel in changed:
        shutil.copy2(work / rel, ctx.out("files", rel))
    ctx.out("ruff_fix.txt").write_text(fix.stdout + fix.stderr, encoding="utf-8")
    ctx.out("ruff_format.txt").write_text(form.stdout + form.stderr, encoding="utf-8")
    ctx.write_json("fmt_report.json", {"changed": changed, "remaining": fix.stdout.strip().splitlines()[-1:]})
    ctx.log.info("fmt.done", changed=len(changed), remaining=fix.stdout.strip().splitlines()[-1:])
    return {"changed": len(changed)}
