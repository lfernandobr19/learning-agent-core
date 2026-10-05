"""Ponte Telegram → agente Cursor local (repo learning-agent).

Permite que a Ravenna consulte o agente Cursor de verdade e repasse a resposta.
Requer CURSOR_API_KEY e pacote cursor-sdk.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from learning_agent.config import (
    CURSOR_AGENT_MODEL,
    CURSOR_API_KEY,
    CURSOR_BRIDGE_ENABLED,
    CURSOR_BRIDGE_TIMEOUT_SECONDS,
    DATA_DIR,
    PROJECT_ROOT,
)

SESSIONS_PATH = DATA_DIR / "cursor_bridge_sessions.json"
CONSULT_LOG = DATA_DIR / "cursor_bridge_consults.jsonl"

CURSOR_CONSULT_KEYWORDS = (
    "fala com o cursor",
    "fale com o cursor",
    "fala com vc",
    "fale com vc",
    "fala com você",
    "fale com você",
    "pergunta ao cursor",
    "pergunta pro cursor",
    "pergunta para o cursor",
    "pergunte ao cursor",
    "pergunte pro cursor",
    "peça ao cursor",
    "peça pro cursor",
    "pede ao cursor",
    "pede pro cursor",
    "consulta o cursor",
    "consulta o agente",
    "consulta o agente cursor",
    "agente cursor",
    "o que o cursor disse",
    "o que vc disse",
    "o que você disse",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_configured() -> bool:
    if not CURSOR_BRIDGE_ENABLED:
        return False
    if not CURSOR_API_KEY:
        return False
    try:
        import cursor_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def configuration_hint() -> str:
    if not CURSOR_API_KEY:
        return "Defina CURSOR_API_KEY no .env (Settings → Cursor → Integrations)."
    try:
        import cursor_sdk  # noqa: F401
    except ImportError:
        return "Instale: pip install cursor-sdk (ou pip install -e \".[cursor]\")."
    if not CURSOR_BRIDGE_ENABLED:
        return "CURSOR_BRIDGE_ENABLED=false no .env."
    return ""


def is_consult_request(text: str) -> bool:
    t = text.lower().strip()
    if t.startswith("/cursor"):
        return True
    if t in {"/cursor", "/cursor reset", "/cursor new"}:
        return True
    return any(k in t for k in CURSOR_CONSULT_KEYWORDS)


def _load_sessions() -> dict[str, Any]:
    if not SESSIONS_PATH.is_file():
        return {"users": {}}
    try:
        data = json.loads(SESSIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"users": {}}
    except json.JSONDecodeError:
        return {"users": {}}


def _save_sessions(data: dict[str, Any]) -> None:
    SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_session(user_id: str) -> None:
    data = _load_sessions()
    data.get("users", {}).pop(str(user_id), None)
    _save_sessions(data)


def _get_session(user_id: str) -> dict[str, Any]:
    return (_load_sessions().get("users") or {}).get(str(user_id)) or {}


def _set_session(user_id: str, agent_id: str) -> None:
    data = _load_sessions()
    users = data.setdefault("users", {})
    users[str(user_id)] = {"agent_id": agent_id, "updated_at": _utcnow()}
    _save_sessions(data)


def _log_consult(payload: dict[str, Any]) -> None:
    CONSULT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CONSULT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _strip_consult_prefix(text: str) -> str:
    t = text.strip()
    if t.lower().startswith("/cursor"):
        rest = t.split(maxsplit=1)
        return rest[1].strip() if len(rest) > 1 else ""
    for prefix in (
        "fala com o cursor",
        "fale com o cursor",
        "fala com vc",
        "fale com vc",
        "fala com você",
        "fale com você",
        "pergunta ao cursor",
        "pergunta pro cursor",
        "consulta o cursor",
        "consulta o agente cursor",
        "pergunte ao cursor",
        "pergunte pro cursor",
        "peça ao cursor",
        "peça pro cursor",
    ):
        if t.lower().startswith(prefix):
            return t[len(prefix) :].strip(" :—-")
    return t


def build_context_block(*, include_finance: bool = True) -> str:
    lines = [
        "CONTEXTO (consulta via Telegram — usuário aguarda resposta factual):",
        f"Repositório: {PROJECT_ROOT}",
        "Você é o agente Cursor local deste repo. Responda em português, direto.",
        "Não invente mudanças aplicadas — verifique arquivos/dados se perguntarem.",
    ]
    if include_finance:
        try:
            from learning_agent.core import finance_status, finance_training_directives

            status = finance_status.build_finance_status(fast=True)
            lines.append("\n--- Finance-lead ---")
            lines.append(finance_status.format_finance_telegram_message(status, fast=True))
            lines.append(finance_training_directives.format_status_summary())
        except Exception as exc:
            lines.append(f"(status finance indisponível: {exc})")
    try:
        from learning_agent.core import user_context

        geo = user_context.format_system_block()
        if geo:
            lines.append("\n--- Utilizador (Ravenna) ---")
            lines.append(geo)
    except Exception:
        pass
    return "\n".join(lines)


def _extract_run_text(run: Any) -> str:
    chunks: list[str] = []
    try:
        for message in run.messages():
            if getattr(message, "type", None) != "assistant":
                continue
            msg = getattr(message, "message", None)
            content = getattr(msg, "content", None) if msg else None
            if not content:
                continue
            for block in content:
                if getattr(block, "type", None) == "text":
                    chunks.append(getattr(block, "text", "") or "")
    except Exception:
        pass
    text = "\n".join(c for c in chunks if c).strip()
    if text:
        return text
    result = getattr(run, "result", None)
    if result is not None:
        final = getattr(result, "result", None) or result
        if isinstance(final, str) and final.strip():
            return final.strip()
    try:
        alt = run.text()
        if isinstance(alt, str) and alt.strip():
            return alt.strip()
    except Exception:
        pass
    return ""


def consult(
    user_id: str,
    user_message: str,
    *,
    reset: bool = False,
    include_finance_context: bool = True,
) -> dict[str, Any]:
    """Consulta o agente Cursor (resume sessão por user_id quando possível)."""
    if reset:
        reset_session(user_id)

    question = _strip_consult_prefix(user_message).strip()
    if question.lower() in {"reset", "new", "nova", "novo"}:
        reset_session(user_id)
        return {"success": True, "reply": "Sessão Cursor reiniciada. Envie sua pergunta.", "reset": True}

    if not question:
        return {
            "success": False,
            "error": "Uso: /cursor <pergunta> ou «fala com o cursor: …»",
        }

    if not is_configured():
        return {"success": False, "error": configuration_hint() or "Bridge Cursor indisponível."}

    from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

    session = _get_session(user_id)
    agent_id = session.get("agent_id")
    context = build_context_block(include_finance=include_finance_context)
    if agent_id:
        prompt = question
    else:
        prompt = f"{context}\n\nPERGUNTA DO USUÁRIO (via Telegram/Ravenna):\n{question}"

    opts = AgentOptions(
        api_key=CURSOR_API_KEY,
        model=CURSOR_AGENT_MODEL,
        local=LocalAgentOptions(cwd=str(PROJECT_ROOT)),
    )

    started = _utcnow()
    try:
        if agent_id:
            agent_ctx = Agent.resume(agent_id, opts)
        else:
            agent_ctx = Agent.create(
                api_key=CURSOR_API_KEY,
                model=CURSOR_AGENT_MODEL,
                local=LocalAgentOptions(cwd=str(PROJECT_ROOT)),
            )

        with agent_ctx as agent:
            if not agent_id:
                _set_session(user_id, agent.id)
            run = agent.send(prompt)
            try:
                run.wait(timeout=CURSOR_BRIDGE_TIMEOUT_SECONDS)
            except TypeError:
                run.wait()
            status = getattr(run, "status", None) or getattr(getattr(run, "result", None), "status", "unknown")
            reply = _extract_run_text(run)
            if status == "error" and not reply:
                reply = "O agente Cursor executou mas retornou erro. Tente reformular a pergunta."
            if not reply:
                reply = "Consulta concluída, mas sem texto na resposta."

        outcome = {
            "success": status != "error",
            "reply": reply[:MAX_REPLY_LEN],
            "status": status,
            "agent_id": _get_session(user_id).get("agent_id"),
            "model": CURSOR_AGENT_MODEL,
        }
    except CursorAgentError as exc:
        outcome = {
            "success": False,
            "error": f"Cursor SDK: {exc}",
            "retryable": getattr(exc, "is_retryable", False),
        }
    except Exception as exc:
        err = str(exc)[:400]
        if "10038" in err or "não é um soquete" in err.lower():
            err = (
                "Bridge Cursor local falhou no Windows (cursor-sdk). "
                "Use /cursor a partir de WSL/Linux ou aguarde correção do SDK. "
                f"Detalhe: {err}"
            )
        outcome = {"success": False, "error": err}

    _log_consult(
        {
            "at": started,
            "user_id": user_id,
            "question": question[:500],
            "success": outcome.get("success"),
            "error": outcome.get("error"),
            "agent_id": outcome.get("agent_id"),
        }
    )
    return outcome


MAX_REPLY_LEN = 3500


def format_consult_reply(result: dict[str, Any]) -> str:
    if not result.get("success"):
        err = result.get("error", "erro desconhecido")
        return f"Não consegui consultar o Cursor.\n\n{err}"
    body = result.get("reply", "").strip()
    header = "Resposta do agente Cursor (repo local):"
    footer = f"\n\n— bridge Cursor ({result.get('model', '?')})"
    if len(body) > MAX_REPLY_LEN - len(header) - len(footer):
        body = body[: MAX_REPLY_LEN - len(header) - len(footer) - 20] + "\n…[truncado]"
    return f"{header}\n\n{body}{footer}"


def chat_rules_snippet() -> str:
    if not is_configured():
        hint = configuration_hint()
        return (
            "CONSULTA CURSOR: indisponível. "
            f"{hint} "
            "Enquanto isso, use /apply para executar sugestões no motor local."
        )
    return (
        "CONSULTA CURSOR: para falar com o agente Cursor DE VERDADE (este repo), "
        "diga «fala com o cursor: …» ou /cursor <pergunta>. "
        "Canais nomeados (ex. teatrinho): /cursor targets | /cursor bind teatrinho current | "
        "/cursor @teatrinho: <msg>. A Ravenna repassa a resposta factual — não simule o Cursor."
    )


def run_consult_async(
    user_id: str,
    message: str,
    *,
    on_complete: Callable[[dict[str, Any]], None],
    reset: bool = False,
) -> None:
    """Executa consulta (para Telegram — pode demorar minutos)."""
    result = consult(user_id, message, reset=reset)
    on_complete(result)
