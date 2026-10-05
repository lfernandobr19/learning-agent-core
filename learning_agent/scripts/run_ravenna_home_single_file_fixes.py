#!/usr/bin/env python3
"""Passo 2 — gemma4 corrige 1 arquivo por run (Ravenna Home completo)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT / "scripts" / "host-gpu.env")

from ravenna_home_runtime import (  # noqa: E402
    autonomy_payload,
    check_api_ready,
    cooldown,
    cooldown_seconds,
    load_host_env,
    orchestrator_log,
    post_autonomy,
    safe_mode,
)

load_host_env()

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
CONV = os.environ.get("RAVENNA_HOME_CONV", "conv-df320529dac4")
LOG = ROOT / "data" / "diagnostics" / "ravenna-home-single-file-fixes.jsonl"
LOCK = ROOT / "data" / "diagnostics" / "ravenna-home-single-file-fixes.lock"

SINGLE_FILE_JOBS: list[dict[str, str]] = [
    {
        "id": "f1-test-health",
        "path": "ravenna-home/backend/tests/test_health.py",
        "brief": (
            "Substitua SOMENTE `ravenna-home/backend/tests/test_health.py` por pytest válido com "
            "TestClient FastAPI testando GET /health (status ok). Arquivo COMPLETO em um ```write```."
        ),
    },
    {
        "id": "f2-home-devices",
        "path": "ravenna-home/tools/home_devices.py",
        "brief": (
            "Substitua SOMENTE `ravenna-home/tools/home_devices.py` — funções async seguras "
            "list_lights, toggle_light, activate_scene. Sem erro de sintaxe. Um ```write``` completo."
        ),
    },
    {
        "id": "f3-chat-mobile",
        "path": "learning_agent/core/chat.py",
        "brief": (
            "Adicione channel `mobile` em `learning_agent/core/chat.py`: greeting PT-BR Ravenna Home "
            "e system prompt para assistente doméstico. Use ```patch``` cirúrgico ou ```write``` "
            "somente se necessário — NÃO reescreva o arquivo inteiro."
        ),
    },
    {
        "id": "f4-manifest",
        "path": "agents/projects/ravenna-home/manifest.yaml",
        "brief": (
            "Substitua SOMENTE `agents/projects/ravenna-home/manifest.yaml` no padrão backend-lead: "
            "version, archetype custom, learning on, mcp_tools, on_failure, files."
        ),
    },
    {
        "id": "f5-curriculum",
        "path": "agents/curricula/ravenna-home.yaml",
        "brief": (
            "Substitua SOMENTE `agents/curricula/ravenna-home.yaml` — YAML válido, agent ravenna-home, "
            "milestones L2–L5 (HA, PWA, distillation)."
        ),
    },
]


def _acquire_lock() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            old = json.loads(LOCK.read_text(encoding="utf-8"))
            pid = int(old.get("pid", 0))
            if pid > 0:
                import subprocess

                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if str(pid) in r.stdout:
                    print(f"Outro run ativo (pid={pid}). Use --force para substituir.", file=sys.stderr)
                    raise SystemExit(3)
        except (json.JSONDecodeError, ValueError, OSError):
            pass
    LOCK.write_text(
        json.dumps({"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def _release_lock() -> None:
    try:
        LOCK.unlink(missing_ok=True)
    except OSError:
        pass


def _wait_api(label: str, max_wait: int = 120) -> bool:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if check_api_ready():
            return True
        print(f"  API offline — aguardando ({label})...", flush=True)
        orchestrator_log(event="api_wait", label=label)
        time.sleep(5)
    return False


def _log(**row: Any) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **row}, ensure_ascii=False) + "\n")


def _file_ok(rel: str) -> bool:
    p = ROOT / rel
    if not p.is_file():
        return _file_on_vm(rel)
    if rel.endswith("test_health.py"):
        import subprocess

        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_health.py", "-q"],
            cwd=str(ROOT / "ravenna-home/backend"),
            capture_output=True,
            timeout=60,
        )
        return r.returncode == 0
    if rel.endswith("home_devices.py"):
        import subprocess

        r = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True)
        return r.returncode == 0
    if rel.endswith("chat.py"):
        return "mobile" in p.read_text(encoding="utf-8", errors="replace")
    if rel.endswith("manifest.yaml"):
        t = p.read_text(encoding="utf-8")
        return "archetype:" in t and len(t) > 200
    if rel.endswith("ravenna-home.yaml"):
        t = p.read_text(encoding="utf-8")
        return "milestones:" in t and "agent:" in t
    return True


def _file_on_vm(rel: str) -> bool:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        return False
    try:
        import paramiko

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(os.environ.get("RAVENNA_VM_HOST", "ravenna-vm"), username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=pwd, timeout=20)
        for base in ("/home/<USER>/learning-agent", "/app"):
            _, out, _ = client.exec_command(f"test -f {base}/{rel} && echo OK", timeout=10)
            if "OK" in out.read().decode(errors="replace"):
                client.close()
                return True
        client.close()
    except Exception:
        pass
    return False


def run_job(job: dict[str, str]) -> dict[str, Any]:
    if not _wait_api(job["id"]):
        row = {"job": job["id"], "path": job["path"], "status": 0, "elapsed_s": 0, "blocks": 0, "changed": [], "file_ok": False, "error": "api_down"}
        _log(**row)
        return row
    print(f"  -> POST autonomy/run ({job['id']})...", flush=True)
    orchestrator_log(event="job_start", job=job["id"], path=job["path"])
    payload = autonomy_payload(
        job["brief"] + "\n\nUse get_project_lessons. Um arquivo só. Não peça confirmação.",
        conversation_id=CONV,
    )
    try:
        r, elapsed = post_autonomy(payload, label=job["id"])
    except Exception as exc:
        row = {
            "job": job["id"],
            "path": job["path"],
            "status": 0,
            "elapsed_s": 0,
            "blocks": 0,
            "changed": [],
            "file_ok": False,
            "error": str(exc)[:500],
        }
        _log(**row)
        orchestrator_log(event="job_error", job=job["id"], error=str(exc)[:500])
        return row
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text[:1500]}
    autonomy = data.get("autonomy") or {}
    attempts = autonomy.get("attempts") or [{}]
    applied = (attempts[0] if attempts else {}).get("applied") or {}
    ok = _file_ok(job["path"])
    _pull_from_vm(job["path"])
    ok = ok or _file_ok(job["path"])
    row = {
        "job": job["id"],
        "path": job["path"],
        "status": r.status_code,
        "elapsed_s": elapsed,
        "blocks": applied.get("blockCount", 0),
        "changed": applied.get("changedPaths", []),
        "file_ok": ok,
    }
    _log(**row)
    return row


def _pull_from_vm(rel: str) -> None:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        return
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=pwd, timeout=20)
        sftp = client.open_sftp()
        dest = ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        for base in ("/home/<USER>/learning-agent", "/home/<USER>/workspace-pc"):
            try:
                sftp.get(f"{base}/{rel}", str(dest))
                break
            except OSError:
                continue
        sftp.close()
        client.close()
    except Exception:
        pass


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ravenna Home — 1 arquivo por run (gemma4)")
    p.add_argument("--jobs", nargs="*", help="IDs dos jobs (ex. f5-curriculum). Default: todos pendentes")
    p.add_argument("--force", action="store_true", help="Substitui lock de outro processo")
    p.add_argument("--no-cooldown", action="store_true", help="Pula pausa entre jobs (não recomendado)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    if args.force and LOCK.is_file():
        _release_lock()
    _acquire_lock()
    try:
        mode = "SAFE" if safe_mode() else "normal"
        print(f"Ravenna Home single-file fixes [{mode}] — cooldown {cooldown_seconds()}s", flush=True)
        orchestrator_log(event="run_start", mode=mode, jobs=args.jobs or "all")
        if not check_api_ready():
            print("API offline — aguardando até 3 min...", flush=True)
            if not _wait_api("startup", max_wait=180):
                print("API indisponível. Abortando.", file=sys.stderr)
                return 1

        selected = SINGLE_FILE_JOBS
        if args.jobs:
            wanted = set(args.jobs)
            selected = [j for j in SINGLE_FILE_JOBS if j["id"] in wanted]
            if not selected:
                print(f"Nenhum job encontrado: {args.jobs}", file=sys.stderr)
                return 1

        results = []
        for job in selected:
            if _file_ok(job["path"]):
                _log(job=job["id"], skipped=True, reason="already_ok")
                print(f"SKIP {job['id']}", flush=True)
                continue
            print(f"RUN {job['id']}...", flush=True)
            results.append(run_job(job))
            print(f"  blocks={results[-1]['blocks']} file_ok={results[-1]['file_ok']}", flush=True)
            if not args.no_cooldown:
                cooldown(label=job["id"])
        failed = [r for r in results if not r.get("file_ok")]
        print(f"Done — {len(results)} runs, {len(failed)} still failing", flush=True)
        orchestrator_log(event="run_done", runs=len(results), failed=len(failed))
        return 0 if not failed else 2
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
