#!/usr/bin/env python3
"""Diagnóstico A/B/C — isola infra vs motor (gemma4-raven / raven)."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

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

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
OLLAMA = f"http://{os.environ.get('RAVENNA_GPU_HOST', 'pc-do-luis')}:11434"
OUT = ROOT / "data" / "diagnostics" / "motor-diagnostic.json"
MARKER = "ravenna-home/diagnostic-motor-test.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _post_chat(payload: dict[str, Any], *, timeout_read: float = 900.0) -> dict[str, Any]:
    t0 = time.time()
    with httpx.Client(timeout=httpx.Timeout(30.0, read=timeout_read)) as c:
        r = c.post(f"{API}/api/chat", json=payload)
    elapsed = round(time.time() - t0, 1)
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:2000]}
    data["_status"] = r.status_code
    data["_elapsed_s"] = elapsed
    return data


def _post_autonomy(payload: dict[str, Any], *, timeout_read: float = 1200.0) -> dict[str, Any]:
    t0 = time.time()
    with httpx.Client(timeout=httpx.Timeout(30.0, read=timeout_read)) as c:
        r = c.post(f"{API}/api/agent/autonomy/run", json=payload)
    elapsed = round(time.time() - t0, 1)
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:2000]}
    data["_status"] = r.status_code
    data["_elapsed_s"] = elapsed
    return data


def test_preflight() -> dict[str, Any]:
    out: dict[str, Any] = {"test": "preflight", "at": _now()}
    try:
        h = httpx.get(f"{API}/health", timeout=15).json()
        out["api"] = "ok"
        out["llm_models"] = h.get("llm_models")
    except Exception as exc:
        out["api"] = f"fail: {exc}"
    try:
        ollama_base = os.environ.get("CHAT_API_BASE", "").rstrip("/").removesuffix("/v1")
        if not ollama_base:
            ollama_base = OLLAMA
        tags = httpx.get(f"{ollama_base}/api/tags", timeout=15).json()
        out["ollama"] = "ok"
        out["models"] = [m.get("name") for m in tags.get("models", [])[:8]]
    except Exception as exc:
        out["ollama"] = f"fail: {exc}"
    out["passed"] = out.get("api") == "ok" and out.get("ollama") == "ok"
    return out


def test_a_infra() -> dict[str, Any]:
    """A — infra: write mínimo deve aplicar 1 arquivo (workspace /app)."""
    payload = {
        "message": (
            "TESTE DIAGNÓSTICO A (infra). Crie APENAS este arquivo:\n\n"
            f"```write {MARKER}\n"
            "motor-diagnostic-A ok\n"
            "```\n"
            "Nada mais. Arquivo pequeno, bloco write COMPLETO."
        ),
        "mode": "agent",
        "channel": "ide",
        "persist_history": False,
        "auto_apply": True,
        "max_repair_attempts": 0,
        "run_checklist": False,
        "model_size": "32b",
    }
    data = _post_autonomy(payload)
    autonomy = data.get("autonomy") or {}
    attempts = autonomy.get("attempts") or [{}]
    applied = (attempts[0] if attempts else {}).get("applied") or {}
    changed = applied.get("changedPaths") or []
    _pull_from_vm(MARKER)
    local_ok = (ROOT / MARKER).is_file()
    vm_ok = _file_on_vm(MARKER)
    passed = bool(changed) or local_ok or vm_ok
    return {
        "test": "A_infra",
        "at": _now(),
        "hypothesis": "Se falhar, culpa é infra/workspace — não motor",
        "passed": passed,
        "status": data.get("_status"),
        "elapsed_s": data.get("_elapsed_s"),
        "autonomy_passed": autonomy.get("passed"),
        "changed_paths": changed,
        "block_count": applied.get("blockCount", 0),
        "local_file": local_ok,
        "vm_file": vm_ok,
        "message_preview": (data.get("message") or "")[:300],
    }


def test_b_motor() -> dict[str, Any]:
    """B — motor: pytest mínimo em motor-canary (calc.add)."""
    try:
        from run_vast_overnight_motor import _seed_canary_base  # noqa: E402

        _seed_canary_base()
    except Exception:
        pass
    payload = {
        "message": (
            "TESTE DIAGNÓSTICO B (motor). O arquivo motor-canary/calc.py JÁ EXISTE com add(a,b).\n"
            "NÃO altere calc.py. Substitua SOMENTE motor-canary/tests/test_calc.py por teste válido:\n\n"
            "```write motor-canary/tests/test_calc.py\n"
            "from calc import add\n\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
            "```\n"
            "Não altere outros arquivos."
        ),
        "mode": "agent",
        "channel": "ide",
        "persist_history": False,
        "auto_apply": True,
        "max_repair_attempts": 0,
        "run_checklist": False,
        "model_size": os.environ.get("VAST_OVERNIGHT_MODEL_SIZE", "7b"),
    }
    data = _post_autonomy(payload, timeout_read=3600.0)
    autonomy = data.get("autonomy") or {}
    attempts = autonomy.get("attempts") or [{}]
    applied = (attempts[0] if attempts else {}).get("applied") or {}
    changed = applied.get("changedPaths") or []
    _pull_from_vm("motor-canary/tests/test_calc.py")
    _pull_from_vm("motor-canary/calc.py")
    msg = (data.get("message") or "").lower()
    quality_flags = {
        "has_write_block": "```write" in msg,
        "mentions_add": "add" in msg or "test_add" in msg,
        "nonsense_import": any(x in msg for x in ("artisan", "from artisan", "thought")),
        "empty_or_tiny": len(data.get("message") or "") < 40,
    }
    pytest_ok = _pytest_canary_passes()
    motor_ok = pytest_ok and not quality_flags["nonsense_import"] and not quality_flags["empty_or_tiny"]
    return {
        "test": "B_motor",
        "at": _now(),
        "hypothesis": "Se A passa e B falha, culpa é motor (qualidade/truncamento)",
        "passed": motor_ok,
        "status": data.get("_status"),
        "elapsed_s": data.get("_elapsed_s"),
        "autonomy_passed": autonomy.get("passed"),
        "changed_paths": changed,
        "quality_flags": quality_flags,
        "pytest_ok": pytest_ok,
        "message_preview": (data.get("message") or "")[:400],
    }


def test_c_chat() -> dict[str, Any]:
    """C — raven chat: resposta coerente em PT."""
    payload = {
        "message": "Responda em uma frase curta em português: qual é o seu nome e papel?",
        "mode": "chat",
        "channel": "ide",
        "persist_history": False,
        "model_size": "auto",
    }
    data = _post_chat(payload, timeout_read=300.0)
    reply = (data.get("message") or "").strip()
    low = reply.lower()
    ok = len(reply) > 10 and any(x in low for x in ("raven", "gemma", "ravenna", "assistente", "engenheir"))
    return {
        "test": "C_chat_raven",
        "at": _now(),
        "hypothesis": "Se C falha, motor conversacional (raven) com problema",
        "passed": ok,
        "status": data.get("_status"),
        "elapsed_s": data.get("_elapsed_s"),
        "reply": reply[:500],
        "model": data.get("reasoning"),
    }


def _file_on_vm(rel: str) -> bool:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        return False
    try:
        import paramiko

        host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=pwd, timeout=20)
        for base in ("/home/<USER>/learning-agent", "/home/<USER>/workspace-pc"):
            cmd = f"test -f {base}/{rel} && echo OK"
            _, stdout, _ = client.exec_command(cmd, timeout=15)
            if "OK" in stdout.read().decode(errors="replace"):
                client.close()
                return True
        client.close()
    except Exception:
        pass
    return False


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


def _pytest_canary_passes() -> bool:
    _pull_from_vm("motor-canary/tests/test_calc.py")
    _pull_from_vm("motor-canary/calc.py")
    for base in (
        ROOT / "motor-canary",
        ROOT / "learning-agent" / "app" / "motor-canary",
        ROOT / "learning-agent" / "motor-canary",
    ):
        if not (base / "tests/test_calc.py").is_file():
            continue
        if not (base / "calc.py").is_file():
            continue
        calc = (base / "calc.py").read_text(encoding="utf-8", errors="replace")
        if "def add" not in calc:
            continue
        import subprocess

        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_calc.py", "-q"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode == 0:
            return True
    return False


def _pytest_health_passes() -> bool:
    _pull_from_vm("ravenna-home/backend/tests/test_health.py")
    tests_dir = ROOT / "ravenna-home/backend"
    if not (tests_dir / "tests/test_health.py").is_file():
        return False
    import subprocess

    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_health.py", "-q"],
        cwd=str(tests_dir),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return r.returncode == 0


def synthesize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by = {r["test"]: r for r in results}
    a, b, c = by.get("A_infra", {}), by.get("B_motor", {}), by.get("C_chat_raven", {})
    conclusion = []
    if not a.get("passed"):
        conclusion.append("INFRA/WORKSPACE — agente não aplica writes (path, auto_apply ou API)")
    elif not b.get("passed"):
        conclusion.append("MOTOR AGENTE — infra OK mas gemma4 não entrega código válido")
    else:
        conclusion.append("MOTOR AGENTE — OK em escopo mínimo")
    if not c.get("passed"):
        conclusion.append("MOTOR CHAT (raven) — resposta fraca ou vazia")
    else:
        conclusion.append("MOTOR CHAT (raven) — OK")
    if a.get("passed") and b.get("passed") and c.get("passed"):
        verdict = "Motores OK em escopo mínimo; falhas anteriores = escopo + orquestração"
    elif not a.get("passed"):
        verdict = "Causa principal: INFRA/WORKSPACE (não motor)"
    elif a.get("passed") and not b.get("passed"):
        verdict = "Causa principal: MOTOR AGENTE (gemma4-raven)"
    else:
        verdict = "Misto — ver conclusões"
    return {"conclusions": conclusion, "verdict": verdict}


def main() -> int:
    import sys as _sys

    only_a = "--test-a" in _sys.argv
    only_b = "--test-b" in _sys.argv
    print("=== Diagnóstico motor Ravenna A/B/C ===\n")
    results: list[dict[str, Any]] = []

    print("[preflight]")
    pre = test_preflight()
    results.append(pre)
    print(json.dumps(pre, ensure_ascii=False))

    if only_b:
        print("\n[B] Motor agente — teste pytest mínimo...")
        b = test_b_motor()
        results.append(b)
        print(
            f"  passed={b['passed']} pytest={b['pytest_ok']} "
            f"changed={b.get('changed_paths')} ({b['elapsed_s']}s)"
        )
        synth = synthesize(results)
        report = {"at": _now(), "results": results, "synthesis": synth}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n=== TESTE B: {'PASS' if b['passed'] else 'FAIL'} ===")
        print(f"Salvo: {OUT}")
        return 0 if b["passed"] else 1

    print("\n[A] Infra — write 1 arquivo...")
    a = test_a_infra()
    results.append(a)
    print(f"  passed={a['passed']} blocks={a['block_count']} local={a['local_file']} vm={a['vm_file']} ({a['elapsed_s']}s)")

    if only_a:
        synth = synthesize(results)
        report = {"at": _now(), "results": results, "synthesis": synth}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n=== TESTE A: {'PASS' if a['passed'] else 'FAIL'} ===")
        print(f"Salvo: {OUT}")
        return 0 if a["passed"] else 1

    print("\n[B] Motor agente — teste pytest mínimo...")
    b = test_b_motor()
    results.append(b)
    print(f"  passed={b['passed']} pytest={b['pytest_ok']} flags={b['quality_flags']} ({b['elapsed_s']}s)")

    print("\n[C] Motor chat — raven...")
    c = test_c_chat()
    results.append(c)
    print(f"  passed={c['passed']} ({c['elapsed_s']}s)")

    synth = synthesize(results)
    report = {"at": _now(), "results": results, "synthesis": synth}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== VEREDITO ===\n{synth['verdict']}")
    for line in synth["conclusions"]:
        print(f"  - {line}")
    print(f"\nSalvo: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
