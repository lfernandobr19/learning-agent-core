"""Runtime profiles for finance overnight — Vast 32B vs Raven+Groq fallback."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Literal

from learning_agent.config import (
    CHAT_API_BASE,
    CHAT_MODEL,
    DATA_DIR,
    PROJECT_ROOT,
    STUDENT_API_BASE,
    STUDENT_MODEL,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
)

ProfileMode = Literal["vast_32b", "raven_groq", "batch_32b"]

VAST_LOCAL_PORT = int(os.environ.get("VAST_LOCAL_PORT", "11435"))
VAST_MODEL = os.environ.get("OVERNIGHT_VAST_MODEL", "qwen2.5:32b")
RAVEN_MODEL = os.environ.get("OVERNIGHT_RAVEN_MODEL", "raven")
RAVEN_GPU_HOST = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")
OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))
DISTILL_EVERY = int(os.environ.get("FINANCE_OVERNIGHT_DISTILL_EVERY", "3"))
BATCH_32B_EVERY = int(os.environ.get("FINANCE_OVERNIGHT_32B_BATCH_EVERY", "6"))
STATE_PATH = DATA_DIR / "overnight_runtime.json"


def _ollama_tags_url(base: str) -> str:
    return base.rstrip("/").replace("/v1", "") + "/api/tags"


def _probe_ollama(base: str, *, timeout: float = 8.0) -> bool:
    url = _ollama_tags_url(base)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def vast_tunnel_available() -> bool:
    port = VAST_LOCAL_PORT
    return _probe_ollama(f"http://127.0.0.1:{port}")


def raven_ollama_available() -> bool:
    candidates = (
        f"http://127.0.0.1:{OLLAMA_PORT}",
        f"http://{RAVEN_GPU_HOST}:{OLLAMA_PORT}",
        STUDENT_API_BASE.replace("/v1", ""),
        CHAT_API_BASE.replace("/v1", ""),
    )
    seen: set[str] = set()
    for base in candidates:
        if not base or base in seen:
            continue
        seen.add(base)
        if _probe_ollama(base):
            return True
    return False


def _raven_api_base() -> str:
    for base in (
        f"http://127.0.0.1:{OLLAMA_PORT}/v1",
        f"http://{RAVEN_GPU_HOST}:{OLLAMA_PORT}/v1",
        STUDENT_API_BASE,
        CHAT_API_BASE,
    ):
        if _probe_ollama(base.replace("/v1", "")):
            return base if base.endswith("/v1") else f"{base.rstrip('/')}/v1"
    return f"http://{RAVEN_GPU_HOST}:{OLLAMA_PORT}/v1"


def _vast_api_base() -> str:
    return f"http://127.0.0.1:{VAST_LOCAL_PORT}/v1"


def resolve_profile(*, cycle_n: int = 0, prefer_batch_32b: bool = False) -> ProfileMode:
    """vast_32b when tunnel up; batch_32b on scheduled heavy cycles; else raven+Groq."""
    if vast_tunnel_available():
        if prefer_batch_32b or (cycle_n > 0 and cycle_n % BATCH_32B_EVERY == 0):
            return "batch_32b"
        return "vast_32b"
    if raven_ollama_available() or TEACHER_API_KEY:
        return "raven_groq"
    return "raven_groq"


def apply_profile(mode: ProfileMode) -> dict[str, str]:
    """Set process env for student/chat models. Teacher stays Groq when configured."""
    if mode in {"vast_32b", "batch_32b"}:
        base = _vast_api_base()
        model = VAST_MODEL
    else:
        base = _raven_api_base()
        model = RAVEN_MODEL

    os.environ["CHAT_API_BASE"] = base
    os.environ["STUDENT_API_BASE"] = base
    os.environ["CHAT_API_KEY"] = os.environ.get("CHAT_API_KEY", "ollama")
    os.environ["STUDENT_API_KEY"] = os.environ.get("STUDENT_API_KEY", "ollama")
    os.environ["CHAT_MODEL"] = model
    os.environ["STUDENT_MODEL"] = model
    os.environ["OVERNIGHT_RUNTIME_PROFILE"] = mode
    os.environ.setdefault("EVOLUTION_LIGHT_STUDY", "false")
    os.environ.setdefault("AUTO_PROOFS", "false")

    snapshot = {
        "profile": mode,
        "chat_api_base": base,
        "chat_model": model,
        "teacher_model": os.environ.get("TEACHER_MODEL", ""),
        "teacher_api_base": TEACHER_API_BASE,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def configure_for_cycle(*, cycle_n: int) -> dict[str, str]:
    mode = resolve_profile(cycle_n=cycle_n, prefer_batch_32b=False)
    return apply_profile(mode)


def student_api_ready() -> bool:
    profile = os.environ.get("OVERNIGHT_RUNTIME_PROFILE") or resolve_profile()
    if profile in {"vast_32b", "batch_32b"}:
        return vast_tunnel_available()
    return raven_ollama_available() or bool(TEACHER_API_KEY)


def should_distill_teacher(cycle_n: int) -> bool:
    """Fewer distillations per cycle — every N cycles, skip even cycles under load."""
    every = max(2, DISTILL_EVERY)
    return cycle_n % every == 1


def load_snapshot() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
