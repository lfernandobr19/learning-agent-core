"""Respostas Telegram à decisão paper — reply sem digitar /decision."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

REGISTRY_PATH = (
    PROJECT_ROOT / "agents" / "projects" / "finance-lead" / "data" / "telegram_decision_messages.json"
)

APPROVE_WORDS = frozenset(
    {
        "sim",
        "s",
        "ok",
        "approve",
        "aprovo",
        "aprovado",
        "aprovada",
        "confirmo",
        "confirmado",
        "executa",
        "executar",
        "aceito",
        "aceita",
        "yes",
        "👍",
        "✅",
    }
)
REGISTER_WORDS = frozenset(
    {
        "register",
        "registrar",
        "registro",
        "journal",
        "só journal",
        "so journal",
        "apenas journal",
        "nota",
    }
)
REJECT_WORDS = frozenset(
    {
        "nao",
        "não",
        "n",
        "no",
        "rejeito",
        "rejeitar",
        "ignore",
        "ignorar",
        "cancela",
        "cancelar",
        "❌",
        "👎",
    }
)

SEQ_IN_TEXT = re.compile(r"ID:\s*#(\d+)", re.IGNORECASE)


def _read_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        return {"by_message_id": {}}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"by_message_id": {}}
    except json.JSONDecodeError:
        return {"by_message_id": {}}


def _write_registry(data: dict[str, Any]) -> None:
    by_msg = data.get("by_message_id") or {}
    if len(by_msg) > 200:
        # mantém os mais recentes
        items = sorted(by_msg.items(), key=lambda kv: kv[1].get("registered_at", ""), reverse=True)[:200]
        data["by_message_id"] = dict(items)
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def register_decision_message(
    *,
    message_id: int,
    chat_id: int,
    seq: int | str,
    decision_id: str,
) -> None:
    data = _read_registry()
    by_msg = data.setdefault("by_message_id", {})
    by_msg[str(message_id)] = {
        "chat_id": chat_id,
        "seq": int(seq) if str(seq).isdigit() else seq,
        "decision_id": decision_id,
        "registered_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _write_registry(data)


def extract_seq_from_text(text: str) -> str | None:
    m = SEQ_IN_TEXT.search(text or "")
    return m.group(1) if m else None


def parse_decision_reply(text: str) -> str | None:
    """Retorna approve | register | reject | None."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    # comando curto embutido: "approve 2" ou "aprovo"
    parts = raw.split()
    first = parts[0].strip(".,!?")
    if first in {"approve", "aprovo", "aprovado", "confirmo"}:
        return "approve"
    if first in {"register", "registrar", "registro"}:
        return "register"
    if first in {"reject", "rejeito", "nao", "não", "ignore", "ignorar"}:
        return "reject"
    if raw in APPROVE_WORDS or first in APPROVE_WORDS:
        return "approve"
    if raw in REGISTER_WORDS or first in REGISTER_WORDS:
        return "register"
    if raw in REJECT_WORDS or first in REJECT_WORDS:
        return "reject"
    return None


def resolve_decision_ref_from_reply(
    reply_to: dict[str, Any],
    *,
    user_text: str = "",
) -> tuple[str | None, str | None]:
    """Resolve seq/decision_id a partir da mensagem respondida."""
    msg_id = reply_to.get("message_id")
    if msg_id is not None:
        entry = (_read_registry().get("by_message_id") or {}).get(str(msg_id))
        if entry:
            seq = entry.get("seq")
            return (str(seq) if seq is not None else None, entry.get("decision_id"))

    quoted = reply_to.get("text") or ""
    seq = extract_seq_from_text(quoted)
    if seq:
        return seq, None

    # "aprovo 2" na resposta
    parts = (user_text or "").split()
    if len(parts) >= 2 and parts[1].lstrip("#").isdigit():
        return parts[1].lstrip("#"), None

    return None, None


def handle_decision_reply(reply_to: dict[str, Any], user_text: str) -> str | None:
    """Processa resposta a alerta de decisão. None se não for decisão."""
    quoted = reply_to.get("text") or ""
    if "decisao paper" not in quoted.lower() and "decisão paper" not in quoted.lower():
        if not (_read_registry().get("by_message_id") or {}).get(str(reply_to.get("message_id"))):
            return None

    mode = parse_decision_reply(user_text)
    if not mode:
        return (
            "Resposta à decisão paper — use:\n"
            "• sim / aprovo → carteira paper\n"
            "• registrar → só journal\n"
            "• não / ignorar → descarta pendente"
        )

    ref, decision_id = resolve_decision_ref_from_reply(reply_to, user_text=user_text)
    if decision_id:
        ref = decision_id
    elif not ref:
        from learning_agent.core import finance_decision_loop as fdl

        pending = fdl.list_pending_decisions()
        if len(pending) == 1:
            ref = str(pending[0].get("seq") or pending[0].get("decision_id", ""))
        else:
            return "Não identifiquei o # da decisão. Responda à mensagem do alerta ou diga «aprovo #2»."

    from learning_agent.core import finance_decision_loop as fdl

    if mode == "reject":
        resolved = fdl.resolve_decision_ref(ref)
        if not resolved:
            return f"Decisão #{ref} não encontrada ou já processada."
        _dismiss_pending(resolved)
        return f"OK — decisão #{ref} ignorada (removida da fila)."

    result = fdl.approve_decision(ref, mode=mode)
    if not result.get("success"):
        return f"Falhou: {result.get('error', 'erro')}"
    seq = result.get("seq")
    label = f"#{seq}" if seq else ref
    action = "aprovada na carteira" if mode == "approve" else "registrada no journal"
    return (
        f"OK — {label} {action}.\n"
        f"Portfolio atualizado: {result.get('portfolio_updated')}\n"
        f"Trades no journal: {result.get('journal_trades')}\n"
        "/portfolio — ver carteira"
    )


def handle_decision_shortcut(user_text: str) -> str | None:
    """Uma pendência só — «aprovo» sem reply."""
    mode = parse_decision_reply(user_text)
    if not mode or user_text.strip().startswith("/"):
        return None
    from learning_agent.core import finance_decision_loop as fdl

    pending = fdl.list_pending_decisions()
    if len(pending) != 1:
        return None
    ref = str(pending[0].get("seq") or pending[0].get("decision_id", ""))
    fake_reply = {"text": f"ID: #{ref}\nFinance-lead — decisao paper", "message_id": None}
    return handle_decision_reply(fake_reply, user_text)


def _dismiss_pending(decision_id: str) -> None:
    from learning_agent.core import finance_decision_loop as fdl

    doc = fdl._load_pending()
    doc["pending"] = [p for p in doc.get("pending", []) if p.get("decision_id") != decision_id]
    fdl._write_json(fdl.PENDING_PATH, doc)


def decision_reply_hint() -> str:
    return "Responda esta mensagem: sim · aprovo · registrar · não"
