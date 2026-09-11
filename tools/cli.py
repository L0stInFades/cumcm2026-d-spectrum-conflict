#!/usr/bin/env python3
"""Forge control plane (local). Never computes: submits cloud jobs, downloads, verifies hashes.

Examples
    python3 tools/cli.py run ingest                      # new run id, small container
    python3 tools/cli.py run validate --run-id <id>      # continue the same run
    python3 tools/cli.py run q1,q2 --size medium         # sequential stages in one container
    python3 tools/cli.py run q3 --size large --spawn     # detached; poll with `wait`/`status`
    python3 tools/cli.py exec --code 'print(sorted(p.name for p in RUN_DIR.iterdir()))'
    python3 tools/cli.py status                          # manifests of the last run
    python3 tools/cli.py download --stage results        # into artifacts/, verified against manifests
    python3 tools/cli.py release --version v1.0.0        # deliverables into releases/v1.0.0/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT = json.loads((REPO / "configs" / "project.json").read_text(encoding="utf-8"))
APP_FILE = REPO / "forge" / "modal_app.py"
STATE_DIR = REPO / ".forge"
LAST_RUN = STATE_DIR / "last_run"
MODAL = shutil.which("modal") or str(Path.home() / ".local" / "bin" / "modal")


def _sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=REPO, check=False, **kw)


def git_ref() -> dict:
    def out(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False).stdout.strip()
        except OSError:
            return ""

    sha = out("rev-parse", "HEAD") or "nogit"
    return {"git_sha": sha, "branch": out("rev-parse", "--abbrev-ref", "HEAD"), "dirty": bool(out("status", "--porcelain"))}


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + git_ref()["git_sha"][:7]


def remember(run_id: str) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    LAST_RUN.write_text(run_id, encoding="utf-8")


def resolve_run_id(explicit: str | None, create: bool) -> str:
    if explicit:
        remember(explicit)
        return explicit
    if create or not LAST_RUN.exists():
        run_id = new_run_id()
        remember(run_id)
        return run_id
    return LAST_RUN.read_text(encoding="utf-8").strip()


def parse_params(items: list[str] | None) -> dict:
    params: dict = {}
    for item in items or []:
        key, _, raw = item.partition("=")
        try:
            params[key] = json.loads(raw)
        except json.JSONDecodeError:
            params[key] = raw
    return params


def modal_run(args: list[str], detach: bool = False) -> int:
    cmd = [MODAL, "run"] + (["--detach"] if detach else []) + [str(APP_FILE)] + args
    return _sh(cmd).returncode


def cmd_run(ns: argparse.Namespace) -> int:
    stages = [s for s in ns.stage.split(",") if s]
    run_id = resolve_run_id(ns.run_id, create=ns.new_run)
    params = parse_params(ns.param)
    params.update({"code_ref": git_ref(), "size": ns.size, "submitted_at": datetime.now().isoformat(timespec="seconds")})
    if ns.from_run:
        params["from_run"] = ns.from_run
    if ns.profile:
        params["profile"] = ns.profile
    stage = stages[0] if len(stages) == 1 else "all"
    if stage == "all":
        params["stages"] = stages
    args = ["--stage", stage, "--run-id", run_id, "--params", json.dumps(params, ensure_ascii=False), "--size", ns.size]
    if ns.force:
        args.append("--force")
    if ns.spawn:
        args.append("--spawn")
    print(f"run_id={run_id} stages={stages} size={ns.size} spawn={ns.spawn}")
    return modal_run(args, detach=ns.spawn)


def cmd_exec(ns: argparse.Namespace) -> int:
    code = Path(ns.file).read_text(encoding="utf-8") if ns.file else ns.code
    if not code:
        print("provide --code or --file", file=sys.stderr)
        return 2
    run_id = resolve_run_id(ns.run_id, create=False)
    return modal_run(["--stage", "exec", "--run-id", run_id, "--params", json.dumps({"code": code}, ensure_ascii=False)])


def cmd_provision(_: argparse.Namespace) -> int:
    return modal_run(["--stage", "provision"])


STATUS_SNIPPET = r'''
import json
from pathlib import Path
run = RUN_DIR
if not run.exists():
    print("run directory missing:", run)
else:
    rows = []
    for m in sorted(run.glob("*/manifest.json")):
        d = json.loads(m.read_text())
        rows.append((d["stage"], d["status"], d.get("duration_s"), d.get("outputs_digest", "")[:12], len(d.get("outputs", {})), (d.get("error") or {}).get("message", "")[:80]))
    print(f"{'stage':14s} {'status':10s} {'seconds':>9s} {'digest':12s} {'files':>5s}  error")
    for r in rows:
        print(f"{r[0]:14s} {r[1]:10s} {str(r[2]):>9s} {r[3]:12s} {r[4]:5d}  {r[5]}")
    print("run_dir:", run)
'''


def cmd_status(ns: argparse.Namespace) -> int:
    run_id = resolve_run_id(ns.run_id, create=False)
    return modal_run(["--stage", "exec", "--run-id", run_id, "--params", json.dumps({"code": STATUS_SNIPPET})])


def cmd_runs(_: argparse.Namespace) -> int:
    return _sh([MODAL, "volume", "ls", PROJECT["volume"], "runs"]).returncode


def cmd_logs(ns: argparse.Namespace) -> int:
    run_id = resolve_run_id(ns.run_id, create=False)
    code = (
        "from pathlib import Path\n"
        f"p = RUN_DIR / {ns.stage!r} / 'events.jsonl'\n"
        "print(p.read_text()[-%d:] if p.exists() else 'no events for stage')\n" % ns.tail
    )
    return modal_run(["--stage", "exec", "--run-id", run_id, "--params", json.dumps({"code": code})])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dir(root: Path) -> int:
    """Verify every downloaded stage directory against its manifest (transport check only)."""
    problems = 0
    manifests = sorted(root.rglob("manifest.json"))
    if not manifests:
        print(f"no manifests under {root}")
        return 1
    for manifest in manifests:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        stage_dir = manifest.parent
        bad = []
        for rel, meta in data.get("outputs", {}).items():
            file = stage_dir / rel
            if not file.exists():
                bad.append(f"missing {rel}")
            elif sha256(file) != meta["sha256"]:
                bad.append(f"sha256 mismatch {rel}")
        status = "OK " if not bad else "BAD"
        print(f"[{status}] {data.get('stage'):14s} {data.get('status'):10s} files={len(data.get('outputs', {}))} {stage_dir}")
        for b in bad:
            print("      " + b)
        problems += len(bad)
    return 0 if problems == 0 else 1


def cmd_download(ns: argparse.Namespace) -> int:
    run_id = resolve_run_id(ns.run_id, create=False)
    remote = f"runs/{run_id}" + (f"/{ns.stage}" if ns.stage else "")
    dest = REPO / ns.dest / "runs" / run_id / (ns.stage or "")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rc = _sh([MODAL, "volume", "get", "--force", PROJECT["volume"], remote, str(dest)]).returncode
    if rc != 0:
        return rc
    return verify_dir(dest)


def cmd_verify(ns: argparse.Namespace) -> int:
    return verify_dir(Path(ns.path))


def cmd_release(ns: argparse.Namespace) -> int:
    run_id = resolve_run_id(ns.run_id, create=False)
    dest = REPO / "releases" / ns.version
    if dest.exists() and not ns.force:
        print(f"{dest} exists; pass --force to overwrite", file=sys.stderr)
        return 2
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    rc = _sh([MODAL, "volume", "get", "--force", PROJECT["volume"], f"runs/{run_id}/release", str(dest)]).returncode
    if rc != 0:
        return rc
    manifest = json.loads((dest / "release_manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for name, meta in manifest["files"].items():
        file = dest / name
        ok = file.exists() and sha256(file) == meta["sha256"]
        bad += 0 if ok else 1
        print(f"[{'OK ' if ok else 'BAD'}] {name} {meta['bytes']} bytes sha256={meta['sha256'][:16]}")
    print(f"release {ns.version} from run {run_id}: {'verified' if not bad else f'{bad} problems'} -> {dest}")
    return 0 if not bad else 1


def cmd_wait(ns: argparse.Namespace) -> int:
    interpreter = Path(MODAL).read_text(encoding="utf-8", errors="ignore").splitlines()[0].lstrip("#!").strip() if Path(MODAL).exists() else sys.executable
    code = (
        "import json, modal, sys\n"
        f"call = modal.FunctionCall.from_id({ns.call_id!r})\n"
        "print('STAGE_RESULT ' + json.dumps(call.get(), ensure_ascii=False, default=str))\n"
    )
    return _sh([interpreter, "-c", code]).returncode


def cmd_new_run(_: argparse.Namespace) -> int:
    run_id = new_run_id()
    remember(run_id)
    print(run_id)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run one stage or a comma-separated sequence in one container")
    r.add_argument("stage")
    r.add_argument("--run-id")
    r.add_argument("--new-run", action="store_true", help="start a fresh run id")
    r.add_argument("--size", default="small", choices=["small", "medium", "large"])
    r.add_argument("--force", action="store_true", help="re-run even if the stage already completed")
    r.add_argument("--spawn", action="store_true", help="detach: return immediately, poll with status/wait")
    r.add_argument("--from-run", help="copy missing dependency outputs from this earlier run")
    r.add_argument("--profile", help="overlay configs/<profile>.toml")
    r.add_argument("--param", action="append", help="key=value (JSON-parsed) forwarded to the stage")
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("exec", help="run an ad-hoc Python snippet in the cloud against the run directory")
    e.add_argument("--code")
    e.add_argument("--file")
    e.add_argument("--run-id")
    e.set_defaults(fn=cmd_exec)

    sub.add_parser("provision", help="verify the cloud toolchain").set_defaults(fn=cmd_provision)

    s = sub.add_parser("status", help="print manifests of a run")
    s.add_argument("--run-id")
    s.set_defaults(fn=cmd_status)

    lg = sub.add_parser("logs", help="tail the event log of a stage")
    lg.add_argument("stage")
    lg.add_argument("--run-id")
    lg.add_argument("--tail", type=int, default=6000)
    lg.set_defaults(fn=cmd_logs)

    sub.add_parser("runs", help="list runs on the volume").set_defaults(fn=cmd_runs)

    d = sub.add_parser("download", help="download a run (or one stage) into artifacts/ and verify hashes")
    d.add_argument("--run-id")
    d.add_argument("--stage")
    d.add_argument("--dest", default="artifacts")
    d.set_defaults(fn=cmd_download)

    v = sub.add_parser("verify", help="verify a downloaded directory against its manifests")
    v.add_argument("path")
    v.set_defaults(fn=cmd_verify)

    rel = sub.add_parser("release", help="download the release stage into releases/<version>/ and verify")
    rel.add_argument("--version", required=True)
    rel.add_argument("--run-id")
    rel.add_argument("--force", action="store_true")
    rel.set_defaults(fn=cmd_release)

    w = sub.add_parser("wait", help="block on a spawned function call id and print its result")
    w.add_argument("call_id")
    w.set_defaults(fn=cmd_wait)

    sub.add_parser("new-run", help="mint a run id").set_defaults(fn=cmd_new_run)
    return p


def main(argv: list[str] | None = None) -> int:
    os.chdir(REPO)
    ns = build_parser().parse_args(argv)
    return int(ns.fn(ns))


if __name__ == "__main__":
    sys.exit(main())
