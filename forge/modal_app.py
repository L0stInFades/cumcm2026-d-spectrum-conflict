"""Modal application — the only compute surface of this repository.

Local side (tools/cli.py) only submits:
    modal run forge/modal_app.py --stage ingest --run-id <id> --params '{...}' --size small
Inside the container the repository is mounted read-only at /repo and the persistent
volume at /vol; stages write exclusively to /vol/runs/<run_id>/<stage>/.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback
from pathlib import Path

import modal

_HERE = Path(__file__).resolve()
REPO = _HERE.parents[1]


def _load_project() -> dict:
    for candidate in (REPO / "configs" / "project.json", Path("/repo/configs/project.json")):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError("configs/project.json not found next to forge/modal_app.py")


PROJECT = _load_project()
app = modal.App(PROJECT["app"])
volume = modal.Volume.from_name(PROJECT["volume"], create_if_missing=True)

APT_PACKAGES = [
    "texlive-xetex", "texlive-lang-chinese", "texlive-latex-base", "texlive-latex-recommended",
    "texlive-latex-extra", "texlive-science", "texlive-pictures", "texlive-bibtex-extra",
    "texlive-fonts-recommended", "fonts-noto-cjk", "fonts-noto-core", "fonts-droid-fallback", "fonts-wqy-microhei",
    "fontconfig", "poppler-utils", "zip", "unzip",
]
PIP_PACKAGES = [
    "numpy==2.2.6", "scipy==1.15.3", "pandas==2.2.3", "pyarrow==20.0.0", "openpyxl==3.1.5",
    "matplotlib==3.10.3", "scikit-learn==1.6.1", "statsmodels==0.14.4", "ortools==9.12.4544",
    "highspy==1.10.0", "numba==0.61.2", "cvxpy==1.6.5", "networkx==3.4.2", "pydantic==2.11.4",
    "pymupdf==1.26.7", "pytest==8.3.5", "pytest-cov==6.1.1", "hypothesis==6.131.9",
    "ruff==0.11.10", "mypy==1.15.0", "pandas-stubs==2.2.3.250308", "types-openpyxl==3.1.5.20250602",
]
SKIP_PARTS = {
    ".git", "artifacts", "releases", ".forge", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".hypothesis", ".DS_Store",
}


def _ignore(path: Path) -> bool:
    return bool(SKIP_PARTS & set(path.parts)) or path.suffix in {".pyc", ".pyo"}


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(*APT_PACKAGES)
    .pip_install(*PIP_PACKAGES)
    .env({
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "MPLBACKEND": "Agg", "MPLCONFIGDIR": "/tmp/mpl", "PYTHONHASHSEED": "0",
        "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": "/repo",
        "FORGE_REPO": "/repo", "FORGE_VOL": "/vol", "MODAL_IS_REMOTE": "1",
        "TEXMFVAR": "/tmp/texmf-var", "TEXMFCONFIG": "/tmp/texmf-config", "HOME": "/root",
    })
    .add_local_dir(REPO, "/repo", ignore=_ignore)
)

VOLUME_MOUNT = {"/vol": volume}


def _bootstrap() -> None:
    if "/repo" not in sys.path:
        sys.path.insert(0, "/repo")
    os.chdir("/repo")
    Path("/tmp/mpl").mkdir(exist_ok=True)


def _run(stage: str, run_id: str, params_json: str, force: bool) -> dict:
    _bootstrap()
    volume.reload()
    from forge.runner import execute

    params = json.loads(params_json or "{}")
    return execute(stage_name=stage, run_id=run_id, params=params, force=force,
                   repo=Path("/repo"), vol=Path("/vol"), commit=volume.commit)


@app.function(image=image, volumes=VOLUME_MOUNT, cpu=2, memory=4096, timeout=2 * 3600)
def run_small(stage: str, run_id: str, params: str, force: bool) -> dict:
    return _run(stage, run_id, params, force)


@app.function(image=image, volumes=VOLUME_MOUNT, cpu=8, memory=16384, timeout=6 * 3600)
def run_medium(stage: str, run_id: str, params: str, force: bool) -> dict:
    return _run(stage, run_id, params, force)


@app.function(image=image, volumes=VOLUME_MOUNT, cpu=32, memory=65536, timeout=12 * 3600)
def run_large(stage: str, run_id: str, params: str, force: bool) -> dict:
    return _run(stage, run_id, params, force)


@app.function(image=image, volumes=VOLUME_MOUNT, cpu=4, memory=8192, timeout=3600)
def exec_python(code: str, run_id: str) -> str:
    """Run an ad-hoc Python snippet in the cloud (exploration, status, debugging). Never local."""
    _bootstrap()
    volume.reload()
    buffer = io.StringIO()
    scope = {
        "__name__": "__forge_exec__", "RUN_DIR": Path("/vol/runs") / run_id, "VOL": Path("/vol"),
        "REPO": Path("/repo"), "RUNS": Path("/vol/runs"),
    }
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            exec(compile(code, "<forge-exec>", "exec"), scope)  # noqa: S102 - explicit cloud REPL
        except BaseException:  # noqa: BLE001
            traceback.print_exc(file=buffer)
    volume.commit()
    return buffer.getvalue()


@app.function(image=image, volumes=VOLUME_MOUNT, cpu=2, memory=4096, timeout=600)
def provision() -> dict:
    """Prove the toolchain: interpreter, packages, TeX engine, fonts, solver availability."""
    import importlib.metadata
    import subprocess

    _bootstrap()
    info: dict = {"modal_task_id": os.getenv("MODAL_TASK_ID"), "cpu_count": os.cpu_count()}
    info["python"] = sys.version.split()[0]
    info["packages"] = {p.split("==")[0]: importlib.metadata.version(p.split("==")[0]) for p in PIP_PACKAGES}
    info["xelatex"] = subprocess.run(["xelatex", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    info["bibtex"] = subprocess.run(["bibtex", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    info["fc_cjk"] = subprocess.run(["fc-match", "Noto Serif CJK SC"], capture_output=True, text=True).stdout.strip()
    info["kpse"] = {name: bool(subprocess.run(["kpsewhich", name], capture_output=True, text=True).stdout.strip())
                    for name in ("ctexart.cls", "gbt7714.sty", "siunitx.sty", "algorithm2e.sty", "booktabs.sty",
                                 "tikz.sty", "listings.sty", "cleveref.sty", "tcolorbox.sty", "pgfplots.sty")}
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()
    x = model.NewIntVar(0, 10, "x")
    model.Add(x >= 3)
    model.Minimize(x)
    solver = cp_model.CpSolver()
    info["cpsat"] = {"status": solver.StatusName(solver.Solve(model)), "x": solver.Value(x)}
    import highspy

    info["highs"] = highspy.Highs().version()
    from forge.plotting import cjk_font_family

    info["figure_cjk_font"] = cjk_font_family()
    return info


@app.local_entrypoint()
def main(
    stage: str = "ingest",
    run_id: str = "",
    params: str = "{}",
    force: bool = False,
    size: str = "small",
    spawn: bool = False,
) -> None:
    """Submit one stage (or ``all`` with params.stages) to the cloud and print its result."""
    if stage == "provision":
        print("PROVISION " + json.dumps(provision.remote(), ensure_ascii=False, default=str))
        return
    if stage == "exec":
        payload = json.loads(params or "{}")
        print(exec_python.remote(payload.get("code", ""), run_id or "adhoc"))
        return
    fn = {"small": run_small, "medium": run_medium, "large": run_large}[size]
    if spawn:
        call = fn.spawn(stage, run_id, params, force)
        print(f"FUNCTION_CALL_ID {call.object_id}")
        return
    result = fn.remote(stage, run_id, params, force)
    print("STAGE_RESULT " + json.dumps(result, ensure_ascii=False, default=str))
