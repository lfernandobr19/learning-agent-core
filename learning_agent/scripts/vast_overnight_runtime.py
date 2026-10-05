"""Runtime compartilhado — sessão overnight Vast (motor 32B)."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "data" / "diagnostics" / "vast-overnight-motor.jsonl"
STATE = ROOT / "data" / "diagnostics" / "vast-overnight-motor-state.json"


def load_env() -> None:
    for path in (
        ROOT / ".env",
        ROOT / "scripts" / "vast-overnight.env",
        ROOT / "scripts" / "host-gpu.env",
        ROOT / "scripts" / "vast-host.env",
    ):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def log_event(**row: Any) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), **row}, ensure_ascii=False) + "\n")


def save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state() -> dict[str, Any]:
    if not STATE.is_file():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def credit_budget_usd() -> float:
    return float(os.environ.get("VAST_OVERNIGHT_BUDGET_USD", "4"))


def credit_reserve_usd() -> float:
    return float(os.environ.get("VAST_CREDIT_RESERVE_USD", "1"))


def credit_total_usd() -> float:
    return float(os.environ.get("VAST_CREDIT_USD", "9"))


def hourly_usd() -> float:
    return float(os.environ.get("VAST_HOURLY_USD", "0.15"))


def max_fail_streak() -> int:
    return max(1, int(os.environ.get("VAST_OVERNIGHT_MAX_FAIL_STREAK", "2")))


def cooldown_seconds() -> int:
    return max(0, int(os.environ.get("VAST_OVERNIGHT_COOLDOWN_S", "0")))


def read_timeout() -> float:
    return float(os.environ.get("VAST_OVERNIGHT_READ_TIMEOUT", "2400"))


def api_base() -> str:
    return os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")


def vast_ollama_base() -> str:
    host = os.environ.get("VAST_HOST", "").strip()
    port = os.environ.get("VAST_OLLAMA_PORT", "11434")
    if not host:
        raise ValueError("VAST_HOST não definido")
    return f"http://{host}:{port}"


def estimate_plan(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    est_min = sum(int(j.get("est_min", 20)) for j in jobs)
    budget = credit_budget_usd()
    hourly = hourly_usd()
    usable_h = budget / hourly if hourly > 0 else 0
    est_h = est_min / 60
    wall_h = min(est_h, usable_h) if usable_h else est_h
    finish = datetime.now(timezone.utc) + timedelta(hours=wall_h)
    return {
        "jobs": len(jobs),
        "est_minutes_queue": est_min,
        "est_hours_queue": round(est_h, 2),
        "budget_usd": budget,
        "hourly_usd": hourly,
        "usable_hours_in_budget": round(usable_h, 2),
        "predicted_wall_hours": round(wall_h, 2),
        "predicted_finish_utc": finish.isoformat(),
        "credit_total_usd": credit_total_usd(),
        "credit_reserve_usd": credit_reserve_usd(),
    }


def check_api_ready() -> bool:
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{api_base()}/health")
        return r.status_code == 200 and r.json().get("status") == "ok"
    except Exception:
        return False


def ollama_check_base() -> str:
    base = os.environ.get("CHAT_API_BASE", "").rstrip("/").removesuffix("/v1")
    if base:
        return base
    return vast_ollama_base()


def check_vast_ollama() -> bool:
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{ollama_check_base()}/api/tags")
        return r.status_code == 200 and "models" in r.json()
    except Exception:
        return False


def post_autonomy(payload: dict, *, label: str) -> tuple[dict[str, Any], float]:
    url = f"{api_base()}/api/agent/autonomy/run"
    timeout_s = read_timeout()
    result: dict[str, Any] = {"data": None, "err": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, read=timeout_s)) as c:
                r = c.post(url, json=payload)
            try:
                result["data"] = r.json()
            except Exception:
                result["data"] = {"detail": r.text[:2000], "_status": r.status_code}
            result["data"]["_status"] = r.status_code
        except Exception as exc:
            result["err"] = exc
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    t0 = time.time()
    tick = 30
    while not done.wait(timeout=tick):
        elapsed = int(time.time() - t0)
        print(f"  ... {label} ({elapsed}s / max {int(timeout_s)}s)", flush=True)
        log_event(event="heartbeat", label=label, elapsed_s=elapsed)

    elapsed = round(time.time() - t0, 1)
    if result["err"] is not None:
        raise result["err"]
    return result["data"], elapsed


def budget_exceeded(started_at: float) -> bool:
    elapsed_h = (time.time() - started_at) / 3600
    return elapsed_h * hourly_usd() >= credit_budget_usd()
