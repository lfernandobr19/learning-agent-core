"""Roteamento de motores cloud na IDE (Groq / DeepSeek) vs Ollama local."""

from __future__ import annotations

from typing import Any

from learning_agent.config import (
    CHAT_API_BASE,
    CHAT_API_KEY,
    CHAT_MODEL,
    CHAT_MODEL_FAST,
    DEEPSEEK_API_BASE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    DEEPSEEK_MODEL_FAST,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
)


def resolve_ide_chat_endpoint(
    *,
    engine: str | None,
    task_mode: str,
    resolved_size: str,
    model_size_requested: str,
) -> dict[str, Any] | None:
    """
    IDE Ask: 0.5b → Ollama local (None).
    Ask/Agent + DeepSeek → API cloud com tool loop quando engine=deepseek_pro.
    Ask + Groq → TEACHER_*; Agent + Groq → None (Ollama local padrão).
    """
    mode = (task_mode or "chat").strip().lower()
    raw_size = (model_size_requested or "auto").strip().lower()
    eng = (engine or "groq").strip().lower().replace("-", "_")
    flash_engine = eng in {"deepseek_flash", "deepseek_v4_flash"}
    pro_engine = eng in {"deepseek", "deepseek_pro", "deepseek_v4", "deepseek_v4_pro"}

    # Raven local só quando o seletor pede 0.5b — NUNCA quando DeepSeek está explícito.
    if not flash_engine and not pro_engine and mode != "agent" and (
        resolved_size == "0.5b" or raw_size == "0.5b" or mode == "fast"
    ):
        return None

    if flash_engine or pro_engine:
        if not DEEPSEEK_API_KEY:
            raise ValueError(
                "DEEPSEEK_API_KEY não configurada no servidor. "
                "Adicione no .env e reinicie o backend."
            )
        want_flash = flash_engine or raw_size in {"fast", "flash"}
        model = DEEPSEEK_MODEL_FAST if want_flash else DEEPSEEK_MODEL
        return {
            "base_url": DEEPSEEK_API_BASE,
            "api_key": DEEPSEEK_API_KEY,
            "model": model,
            "label": f"deepseek/{model}",
        }

    if mode == "agent":
        return None

    if eng in {"groq", "teacher", "cloud"} and TEACHER_API_KEY:
        return {
            "base_url": TEACHER_API_BASE,
            "api_key": TEACHER_API_KEY,
            "model": TEACHER_MODEL,
            "label": f"groq/{TEACHER_MODEL}",
        }

    return None


def local_chat_endpoint(*, fast: bool = False) -> dict[str, Any]:
    return {
        "base_url": CHAT_API_BASE,
        "api_key": CHAT_API_KEY,
        "model": CHAT_MODEL_FAST if fast else CHAT_MODEL,
        "label": f"ollama/{CHAT_MODEL_FAST if fast else CHAT_MODEL}",
    }


def resolve_ide_chat_endpoint_chain(
    *,
    engine: str | None,
    task_mode: str,
    resolved_size: str,
    model_size_requested: str,
) -> list[dict[str, Any]]:
    """Cadeia de failover ordenada: primário → DeepSeek → Groq → raven local.

    Sempre tenta o primário (engine/tamanho); se não disponível ou falhar,
    o chamador percorre a lista. Deduplica por label.
    """
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(ep: dict[str, Any] | None) -> None:
        if not ep:
            return
        key = str(ep.get("label") or ep.get("model") or "")
        if not key or key in seen:
            return
        seen.add(key)
        chain.append(ep)

    try:
        primary = resolve_ide_chat_endpoint(
            engine=engine,
            task_mode=task_mode,
            resolved_size=resolved_size,
            model_size_requested=model_size_requested,
        )
    except ValueError:
        primary = None
    add(primary)

    # DeepSeek como fallback (se não for o primário)
    if DEEPSEEK_API_KEY:
        add(
            {
                "base_url": DEEPSEEK_API_BASE,
                "api_key": DEEPSEEK_API_KEY,
                "model": DEEPSEEK_MODEL,
                "label": f"deepseek/{DEEPSEEK_MODEL}",
            }
        )

    # Groq (TEACHER) como fallback
    if TEACHER_API_KEY:
        add(
            {
                "base_url": TEACHER_API_BASE,
                "api_key": TEACHER_API_KEY,
                "model": TEACHER_MODEL,
                "label": f"groq/{TEACHER_MODEL}",
            }
        )

    # raven local (Ollama) — último recurso
    add(local_chat_endpoint(fast=False))

    return chain
