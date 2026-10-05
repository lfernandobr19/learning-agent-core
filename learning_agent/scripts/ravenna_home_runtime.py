"""Configuração compartilhada — modo seguro para orquestração Ravenna Home (RX 580 8 GB)."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
HEARTBEAT_LOG = ROOT / "data" / "diagnostics" / "ravenna-home-orchestrator.jsonl"


def load_host_env() -> None:
    for path in (ROOT / ".env", ROOT / "scripts" / "host-gpu.env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def safe_mode() -> bool:
    return os.environ.get("RAVENNA_SAFE_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}


def model_size() -> str:
    default = "auto" if safe_mode() else "32b"
    return os.environ.get("RAVENNA_HOME_MODEL_SIZE", default).strip() or default


def cooldown_seconds() -> int:
    default = "300" if safe_mode() else "15"
    return max(0, int(os.environ.get("RAVENNA_HOME_COOLDOWN_S", default)))


def max_repair_attempts(*, supervisor: bool = False) -> int:
    if supervisor:
        default = "1" if safe_mode() else "2"
        return max(0, int(os.environ.get("RAVENNA_HOME_MAX_REPAIR", default)))
    return max(0, int(os.environ.get("RAVENNA_HOME_MAX_REPAIR", "1")))


def read_timeout() -> float:
    default = "2400" if safe_mode() else "3600"
    return float(os.environ.get("RAVENNA_HOME_READ_TIMEOUT", default))


def run_timeout() -> float:
    default = "2400" if safe_mode() else "5400"
    return float(os.environ.get("RAVENNA_HOME_TIMEOUT", default))


def heartbeat_interval() -> int:
    return max(15, int(os.environ.get("RAVENNA_HOME_HEARTBEAT_S", "30")))


def orchestrator_log(**row: Any) -> None:
    HEARTBEAT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with HEARTBEAT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"at": datetime.now(timezone.utc).isoformat(), **row}, ensure_ascii=False) + "\n"
        )


def api_base() -> str:
    return os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")


def check_api_ready(*, timeout: float = 10.0) -> bool:
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(f"{api_base()}/health")
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def post_autonomy(
    payload: dict,
    *,
    label: str,
    endpoint: str = "/api/agent/autonomy/run",
) -> tuple[httpx.Response, float]:
    """POST com heartbeat — evita silêncio de 15–40 min sem feedback."""
    url = f"{api_base()}{endpoint}"
    timeout_s = read_timeout()
    result: dict[str, Any] = {"resp": None, "err": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=timeout_s)) as c:
                result["resp"] = c.post(url, json=payload)
        except Exception as exc:
            result["err"] = exc
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    t0 = time.time()
    tick = heartbeat_interval()
    while not done.wait(timeout=tick):
        elapsed = int(time.time() - t0)
        print(f"  ... {label} aguardando API ({elapsed}s / max {int(timeout_s)}s)", flush=True)
        orchestrator_log(event="heartbeat", label=label, elapsed_s=elapsed, max_s=int(timeout_s))

    elapsed = round(time.time() - t0, 1)
    if result["err"] is not None:
        orchestrator_log(event="post_error", label=label, elapsed_s=elapsed, error=str(result["err"]))
        raise result["err"]
    resp: httpx.Response = result["resp"]
    orchestrator_log(event="post_done", label=label, elapsed_s=elapsed, status=resp.status_code)
    return resp, elapsed


def gpu_host() -> str:
    return os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis").strip()


def agent_model() -> str:
    return os.environ.get("OLLAMA_MODEL", "gemma4-raven").strip()


def unload_gpu_model() -> bool:
    """Descarrega modelo do Ollama no PC (libera VRAM entre jobs)."""
    if not safe_mode():
        return False
    url = f"http://{gpu_host()}:{os.environ.get('OLLAMA_PORT', '11434')}/api/generate"
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.post(url, json={"model": agent_model(), "prompt": "", "keep_alive": 0})
        return r.status_code == 200
    except Exception:
        return False


def cooldown(*, label: str = "") -> None:
    secs = cooldown_seconds()
    if secs <= 0:
        return
    suffix = f" ({label})" if label else ""
    print(f"  cooldown {secs}s{suffix} — descarregando GPU...", flush=True)
    orchestrator_log(event="cooldown_start", label=label, seconds=secs)
    if unload_gpu_model():
        print("  GPU model unloaded", flush=True)
    remaining = secs
    tick = min(60, heartbeat_interval())
    while remaining > 0:
        step = min(tick, remaining)
        time.sleep(step)
        remaining -= step
        if remaining > 0:
            print(f"  cooldown ... {remaining}s restantes{suffix}", flush=True)
            orchestrator_log(event="cooldown_tick", label=label, remaining_s=remaining)
    orchestrator_log(event="cooldown_done", label=label)


def autonomy_payload(
    message: str,
    *,
    conversation_id: str,
    project_root: str | None = None,
    run_checklist: bool = False,
    supervisor: bool = False,
) -> dict:
    return {
        "message": message,
        "mode": "agent",
        "channel": "ide",
        "conversation_id": conversation_id,
        "persist_history": True,
        "auto_apply": True,
        "max_repair_attempts": max_repair_attempts(supervisor=supervisor),
        "project_root": project_root,
        "run_checklist": run_checklist,
        "model_size": model_size(),
    }
