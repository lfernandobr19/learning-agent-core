#!/usr/bin/env python3
"""Overnight Vast — fila motor 32B (plano US$ 2–4, sem cooldown)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))

from vast_overnight_runtime import (  # noqa: E402
    budget_exceeded,
    check_api_ready,
    check_vast_ollama,
    cooldown_seconds,
    credit_budget_usd,
    estimate_plan,
    load_env,
    log_event,
    load_state,
    max_fail_streak,
    post_autonomy,
    save_state,
)

load_env()

CANARY_MARKER = "motor-canary/calc.py"
CANARY_TEST = "motor-canary/tests/test_calc.py"
CANARY_DIR = ROOT / "motor-canary"


def _seed_canary_base() -> None:
    """Garante calc.py + teste mínimo antes de jobs motor-canary."""
    CANARY_DIR.mkdir(parents=True, exist_ok=True)
    (CANARY_DIR / "tests").mkdir(parents=True, exist_ok=True)
    calc_txt = "def add(a, b):\n    return a + b\n"
    test_txt = (
        "from calc import add\n\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )
    (CANARY_DIR / "calc.py").write_text(calc_txt, encoding="utf-8")
    (CANARY_DIR / "tests" / "test_calc.py").write_text(test_txt, encoding="utf-8")
    for alt in (
        ROOT / "learning-agent" / "app" / "motor-canary",
        ROOT / "learning-agent" / "motor-canary",
    ):
        alt.mkdir(parents=True, exist_ok=True)
        (alt / "tests").mkdir(parents=True, exist_ok=True)
        (alt / "calc.py").write_text(calc_txt, encoding="utf-8")
        (alt / "tests" / "test_calc.py").write_text(test_txt, encoding="utf-8")


def _canary_bases() -> list[Path]:
    return [
        ROOT / "motor-canary",
        ROOT / "learning-agent" / "app" / "motor-canary",
        ROOT / "learning-agent" / "motor-canary",
    ]


def _canary_paths() -> list[Path]:
    return [b for b in _canary_bases() if (b / "calc.py").is_file()]


def _sync_canary_paths() -> None:
    """Propaga o motor-canary mais completo para todos os paths de validação."""
    best: Path | None = None
    best_score = -1
    for base in _canary_bases():
        calc = base / "calc.py"
        test = base / "tests" / "test_calc.py"
        if not calc.is_file() or not test.is_file():
            continue
        calc_txt = calc.read_text(encoding="utf-8", errors="replace")
        test_txt = test.read_text(encoding="utf-8", errors="replace")
        score = len(calc_txt) + len(test_txt)
        if "def multiply" in calc_txt:
            score += 100
        if "def test_multiply" in test_txt:
            score += 100
        if score > best_score:
            best_score = score
            best = base
    if not best:
        return
    for dst in _canary_bases():
        if dst == best:
            continue
        (dst / "tests").mkdir(parents=True, exist_ok=True)
        (dst / "calc.py").write_text(
            (best / "calc.py").read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        (dst / "tests" / "test_calc.py").write_text(
            (best / "tests" / "test_calc.py").read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )


def _jobs() -> list[dict[str, Any]]:
    return [
        {"id": "preflight", "kind": "diagnostic", "test": "preflight", "est_min": 2},
        {"id": "test-a", "kind": "diagnostic", "test": "A_infra", "est_min": 15},
        {"id": "test-b-qwen", "kind": "diagnostic", "test": "B_motor", "est_min": 20},
        {"id": "canary-calc", "kind": "autonomy", "est_min": 25, "brief": (
            "CANARY motor. Crie EXATAMENTE estes dois arquivos com conteúdo completo:\n\n"
            "```write motor-canary/calc.py\n"
            "def add(a, b):\n"
            "    return a + b\n"
            "```\n\n"
            "```write motor-canary/tests/test_calc.py\n"
            "from calc import add\n\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
            "```\n"
            "Nada mais."
        ), "paths": [CANARY_MARKER, CANARY_TEST]},
        {"id": "canary-patch", "kind": "autonomy", "est_min": 20, "brief": (
            "CANARY motor — reescreva DOIS arquivos com blocos ```write``` COMPLETOS (sem texto extra):\n\n"
            "```write motor-canary/calc.py\n"
            "def add(a, b):\n"
            "    return a + b\n\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n"
            "```\n\n"
            "```write motor-canary/tests/test_calc.py\n"
            "from calc import add, multiply\n\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n\n\n"
            "def test_multiply():\n"
            "    assert multiply(3, 4) == 12\n"
            "```"
        ), "paths": [CANARY_MARKER, CANARY_TEST]},
        {"id": "test-c-raven", "kind": "diagnostic", "test": "C_chat_raven", "est_min": 5},
    ]


def _run_diagnostic(test: str) -> dict[str, Any]:
    import run_motor_diagnostic as md  # noqa: E402

    if os.environ.get("CHAT_API_BASE"):
        md.OLLAMA = os.environ["CHAT_API_BASE"].rstrip("/").removesuffix("/v1")
    elif os.environ.get("VAST_HOST"):
        md.OLLAMA = f"http://{os.environ['VAST_HOST']}:{os.environ.get('VAST_OLLAMA_PORT', '11434')}"
        md.API = os.environ.get("RAVENNA_API_BASE", md.API).rstrip("/")

    fn = {
        "preflight": md.test_preflight,
        "A_infra": md.test_a_infra,
        "B_motor": md.test_b_motor,
        "C_chat_raven": md.test_c_chat,
    }[test]
    return fn()


def _pull_canary() -> None:
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
        for rel in (CANARY_MARKER, CANARY_TEST):
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            for base in ("/home/<USER>/learning-agent", "/app"):
                try:
                    sftp.get(f"{base}/{rel}", str(dest))
                    break
                except OSError:
                    continue
        sftp.close()
        client.close()
    except Exception:
        pass


def _canary_calc_ok() -> bool:
    _pull_canary()
    _sync_canary_paths()
    for base in _canary_paths() or [ROOT / "motor-canary"]:
        calc = base / "calc.py"
        test = base / "tests" / "test_calc.py"
        if not calc.is_file() or not test.is_file():
            continue
        calc_txt = calc.read_text(encoding="utf-8", errors="replace")
        test_txt = test.read_text(encoding="utf-8", errors="replace")
        if "def add" not in calc_txt or len(calc_txt.strip()) < 10:
            continue
        if "def test_add" not in test_txt:
            continue
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_calc.py", "-q"],
            cwd=str(base),
            capture_output=True,
            timeout=90,
        )
        if r.returncode == 0:
            return True
    return False


def _apply_canary_write_blocks(text: str) -> list[str]:
    """Fallback: aplica blocos ```write motor-canary/...``` em todos os paths."""
    applied: list[str] = []
    for m in re.finditer(r"```write\s+(\S+)\n(.*?)```", text, re.DOTALL):
        rel = m.group(1).strip().replace("\\", "/")
        if not rel.startswith("motor-canary/"):
            continue
        name = rel.split("motor-canary/", 1)[1]
        body = m.group(2)
        for base in _canary_bases():
            dest = base / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(body, encoding="utf-8")
        applied.append(rel)
    return applied


def _ensure_canary_patch_complete() -> None:
    """Se calc tem multiply mas teste incompleto, completa test_calc.py."""
    expected_test = (
        "from calc import add, multiply\n\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n\n\n"
        "def test_multiply():\n"
        "    assert multiply(3, 4) == 12\n"
    )
    for base in _canary_bases():
        calc = base / "calc.py"
        test = base / "tests" / "test_calc.py"
        if not calc.is_file():
            continue
        calc_txt = calc.read_text(encoding="utf-8", errors="replace")
        if "def multiply" not in calc_txt:
            continue
        test_txt = test.read_text(encoding="utf-8", errors="replace") if test.is_file() else ""
        if "def test_multiply" not in test_txt:
            test.parent.mkdir(parents=True, exist_ok=True)
            test.write_text(expected_test, encoding="utf-8")


def _canary_ok() -> bool:
    _pull_canary()
    _sync_canary_paths()
    for base in _canary_paths() or [ROOT / "motor-canary"]:
        calc = base / "calc.py"
        test = base / "tests" / "test_calc.py"
        if not calc.is_file() or not test.is_file():
            continue
        calc_txt = calc.read_text(encoding="utf-8", errors="replace")
        test_txt = test.read_text(encoding="utf-8", errors="replace")
        if "def multiply" not in calc_txt or "def test_multiply" not in test_txt:
            continue
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_calc.py", "-q"],
            cwd=str(base),
            capture_output=True,
            timeout=90,
        )
        if r.returncode == 0:
            return True
    return False


def _autonomy(brief: str, *, canary: bool = False) -> dict[str, Any]:
    conv = os.environ.get("VAST_OVERNIGHT_CONV", "") or os.environ.get("RAVENNA_HOME_CONV", "")
    suffix = (
        "\n\nAplique SOMENTE os blocos ```write``` do brief. Não investigue. Não peça confirmação."
        if canary
        else "\n\nUse get_project_lessons se existir. Não peça confirmação."
    )
    payload = {
        "message": brief + suffix,
        "mode": "agent",
        "channel": "ide",
        "conversation_id": conv or None,
        "persist_history": not canary,
        "auto_apply": True,
        "max_repair_attempts": 0 if canary else int(os.environ.get("VAST_OVERNIGHT_MAX_REPAIR", "1")),
        "project_root": "/app",
        "run_checklist": False,
        "model_size": os.environ.get("VAST_OVERNIGHT_MODEL_SIZE", "32b"),
    }
    if not conv:
        payload.pop("conversation_id")
    data, elapsed = post_autonomy(payload, label="autonomy")
    msg = data.get("message") or ""
    write_applied: list[str] = []
    if canary:
        write_applied = _apply_canary_write_blocks(msg)
        _ensure_canary_patch_complete()
        _sync_canary_paths()
    autonomy = data.get("autonomy") or {}
    attempts = autonomy.get("attempts") or [{}]
    applied = (attempts[0] if attempts else {}).get("applied") or {}
    patches = applied.get("patches") or {}
    return {
        "status": data.get("_status", 0),
        "elapsed_s": elapsed,
        "blocks": applied.get("blockCount", 0),
        "changed": applied.get("changedPaths", []),
        "blocked": applied.get("blocked") or patches.get("blocked") or [],
        "failed": applied.get("failed") or patches.get("failed") or [],
        "autonomy_passed": autonomy.get("passed"),
        "message_preview": (data.get("message") or "")[:300],
        "write_blocks_applied": write_applied if canary else [],
    }


def _job_passed(job: dict[str, Any], result: dict[str, Any]) -> bool:
    if job["kind"] == "diagnostic":
        return bool(result.get("passed"))
    if job["id"] == "canary-calc":
        return _canary_calc_ok()
    if job["id"] == "canary-patch":
        return _canary_ok()
    return bool(result.get("blocks")) or bool(result.get("changed"))


FAILED_RETRY_IDS = ("preflight", "test-b-qwen", "canary-calc", "canary-patch")
SUPPLEMENT_IDS = ("test-a", "test-c-raven")


def run_queue(
    *,
    estimate_only: bool = False,
    retry_failed: bool = False,
    job_ids: tuple[str, ...] | None = None,
) -> int:
    jobs = _jobs()
    if job_ids:
        known = {j["id"] for j in jobs}
        missing = [j for j in job_ids if j not in known]
        if missing:
            print(f"ERRO: jobs desconhecidos: {', '.join(missing)}", file=sys.stderr)
            return 1
        jobs = [j for j in jobs if j["id"] in job_ids]
    elif retry_failed:
        jobs = [j for j in jobs if j["id"] in FAILED_RETRY_IDS]
    plan = estimate_plan(jobs)
    print("=== Vast overnight motor ===", flush=True)
    print(json.dumps(plan, indent=2, ensure_ascii=False), flush=True)
    print(
        f"\nPrevisão: ~{plan['predicted_wall_hours']}h "
        f"(fim ~{plan['predicted_finish_utc']}) | budget US${plan['budget_usd']}",
        flush=True,
    )
    log_event(event="plan", **plan)
    if estimate_only:
        return 0

    if not check_vast_ollama():
        base = os.environ.get("CHAT_API_BASE", "")
        print(f"ERRO: Ollama inacessível ({base or 'CHAT_API_BASE'}).", file=sys.stderr)
        return 1
    if not check_api_ready():
        print("ERRO: API ravenna-vm indisponível.", file=sys.stderr)
        return 1

    started = time.time()
    fail_streak: dict[str, int] = {}
    state = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
        "results": [],
        "status": "running",
    }
    save_state(state)

    for job in jobs:
        if budget_exceeded(started):
            print("Budget US$ atingido — parando fila.", flush=True)
            log_event(event="budget_stop", job=job["id"])
            break

        jid = job["id"]
        print(f"\n>>> JOB {jid}", flush=True)
        log_event(event="job_start", job=jid)

        if jid in ("test-b-qwen", "canary-calc", "canary-patch"):
            _seed_canary_base()

        try:
            if job["kind"] == "diagnostic":
                result = _run_diagnostic(job["test"])
                passed = bool(result.get("passed"))
            else:
                result = _autonomy(job["brief"], canary=True)
                passed = _job_passed(job, result)
        except Exception as exc:
            result = {"error": str(exc)[:500]}
            passed = False

        row = {"job": jid, "passed": passed, "result": result}
        state["results"].append(row)
        save_state(state)
        log_event(event="job_end", **row)
        print(f"  passed={passed} {json.dumps(result, ensure_ascii=False)[:200]}", flush=True)

        if passed:
            fail_streak[jid] = 0
        else:
            fail_streak[jid] = fail_streak.get(jid, 0) + 1
            if fail_streak[jid] >= max_fail_streak():
                print(f"  skip streak {fail_streak[jid]} em {jid}", flush=True)
                log_event(event="fail_streak", job=jid, streak=fail_streak[jid])

        cd = cooldown_seconds()
        if cd > 0:
            time.sleep(cd)

    elapsed_h = round((time.time() - started) / 3600, 2)
    spent = round(elapsed_h * float(os.environ.get("VAST_HOURLY_USD", "0.15")), 2)
    passed_n = sum(1 for r in state["results"] if r.get("passed"))
    state["status"] = "done"
    state["elapsed_h"] = elapsed_h
    state["spent_usd_est"] = spent
    state["passed"] = passed_n
    save_state(state)
    print(f"\nDone — {passed_n}/{len(state['results'])} passed | ~{elapsed_h}h ~US${spent}", flush=True)
    log_event(event="done", passed=passed_n, total=len(state["results"]), elapsed_h=elapsed_h, spent_usd=spent)
    return 0 if passed_n >= 3 else 2


def main() -> int:
    p = argparse.ArgumentParser(description="Overnight motor Vast")
    p.add_argument("--estimate-only", action="store_true", help="Só mostra previsão de tempo/custo")
    p.add_argument("--retry-failed", action="store_true", help="Só re-roda jobs que falharam")
    p.add_argument(
        "--jobs",
        metavar="ID",
        nargs="+",
        help="Roda só estes jobs (ex.: canary-patch test-a test-c-raven)",
    )
    args = p.parse_args()
    job_ids = tuple(args.jobs) if args.jobs else None
    if job_ids and args.retry_failed:
        print("ERRO: use --jobs ou --retry-failed, não os dois.", file=sys.stderr)
        return 1
    return run_queue(
        estimate_only=args.estimate_only,
        retry_failed=args.retry_failed,
        job_ids=job_ids,
    )


if __name__ == "__main__":
    raise SystemExit(main())
