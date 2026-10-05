"""Alvos nomeados Cursor (canais) + inbox de handoff.

Limitação: a API/SDK do Cursor NÃO injeta mensagem numa aba Composer
do IDE (UUID do chat). O que dá para fazer:

1. Canal nomeado → agent_id do Cursor SDK (Agent.resume)
2. Inbox em disco (JSONL) que um chat/automação do Cursor lê

Fluxo Teatrinho típico:
  Ravenna envia filme ao Debian → enqueue_handoff("teatrinho", ...)
  → opcionalmente notify_target("teatrinho", prompt)
  → Cursor no canal teatrinho importa para a biblioteca
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR

TARGETS_PATH = DATA_DIR / "cursor_targets.json"
INBOX_DIR = DATA_DIR / "cursor_inbox"

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(name: str) -> str:
    s = (name or "").strip().lower().replace(" ", "-")
    s = _SLUG_RE.sub("-", s).strip("-")
    return s[:64] or "default"


def _load() -> dict[str, Any]:
    if not TARGETS_PATH.is_file():
        return {"targets": {}}
    try:
        data = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"targets": {}}
    except json.JSONDecodeError:
        return {"targets": {}}


def _save(data: dict[str, Any]) -> None:
    TARGETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_targets() -> list[dict[str, Any]]:
    targets = (_load().get("targets") or {})
    rows = []
    for slug, meta in targets.items():
        if not isinstance(meta, dict):
            continue
        rows.append(
            {
                "name": slug,
                "agent_id": meta.get("agent_id") or "",
                "label": meta.get("label") or slug,
                "notes": meta.get("notes") or "",
                "updated_at": meta.get("updated_at") or "",
                "has_agent": bool(meta.get("agent_id")),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return rows


def get_target(name: str) -> dict[str, Any] | None:
    slug = _slug(name)
    meta = (_load().get("targets") or {}).get(slug)
    if not isinstance(meta, dict):
        return None
    return {"name": slug, **meta}


def bind_target(
    name: str,
    *,
    agent_id: str | None = None,
    label: str | None = None,
    notes: str | None = None,
    bind_current_session_user_id: str | None = None,
) -> dict[str, Any]:
    """Associa um nome (ex.: teatrinho) a um agent_id do Cursor SDK.

    Se agent_id vazio e bind_current_session_user_id setado, usa a sessão
    atual do bridge Telegram desse usuário.
    """
    slug = _slug(name)
    aid = (agent_id or "").strip()
    if not aid and bind_current_session_user_id:
        from learning_agent.core import cursor_agent_bridge as bridge

        sess = bridge._get_session(str(bind_current_session_user_id))  # noqa: SLF001
        aid = str(sess.get("agent_id") or "").strip()
    if not aid:
        return {
            "ok": False,
            "error": (
                "Informe agent_id OU rode antes /cursor <msg> e use "
                "`/cursor bind <nome> current` para pegar a sessão atual."
            ),
        }

    data = _load()
    targets = data.setdefault("targets", {})
    prev = targets.get(slug) if isinstance(targets.get(slug), dict) else {}
    entry = {
        "agent_id": aid,
        "label": (label or prev.get("label") or slug).strip(),
        "notes": (notes if notes is not None else prev.get("notes") or "").strip(),
        "updated_at": _utcnow(),
        "created_at": prev.get("created_at") or _utcnow(),
    }
    targets[slug] = entry
    _save(data)
    return {"ok": True, "name": slug, **entry}


def unbind_target(name: str) -> dict[str, Any]:
    slug = _slug(name)
    data = _load()
    targets = data.setdefault("targets", {})
    if slug not in targets:
        return {"ok": False, "error": f"alvo inexistente: {slug}"}
    del targets[slug]
    _save(data)
    return {"ok": True, "removed": slug}


def inbox_path(name: str) -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return INBOX_DIR / f"{_slug(name)}.jsonl"


def enqueue_handoff(
    target: str,
    *,
    kind: str,
    title: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Escreve job no inbox do canal (Cursor pode ler depois)."""
    slug = _slug(target)
    row = {
        "id": f"{_slug(kind)}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "at": _utcnow(),
        "target": slug,
        "kind": (kind or "task").strip(),
        "title": (title or "").strip(),
        "message": (message or "").strip(),
        "payload": payload or {},
        "status": "pending",
    }
    path = inbox_path(slug)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "inbox": str(path), "job": row}


def list_pending(target: str, *, limit: int = 20) -> list[dict[str, Any]]:
    path = inbox_path(target)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("status", "pending") == "pending":
            rows.append(row)
    return rows[-max(1, limit) :]


def notify_target(
    name: str,
    message: str,
    *,
    user_id: str = "system",
    also_inbox: bool = True,
    inbox_kind: str = "notify",
    inbox_title: str = "",
    inbox_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enfileira handoff e, se houver agent_id, consulta o agente Cursor desse canal."""
    target = get_target(name)
    if not target:
        return {
            "ok": False,
            "error": (
                f"Alvo '{_slug(name)}' não existe. "
                "Crie com /cursor bind <nome> current  (depois de um /cursor …) "
                "ou /cursor bind <nome> <agent_id>."
            ),
        }

    out: dict[str, Any] = {"ok": True, "target": target["name"], "agent_id": target.get("agent_id")}
    if also_inbox:
        out["inbox"] = enqueue_handoff(
            target["name"],
            kind=inbox_kind,
            title=inbox_title or f"Notify {target['name']}",
            message=message,
            payload=inbox_payload,
        )

    agent_id = str(target.get("agent_id") or "").strip()
    if not agent_id:
        out["consult"] = {"skipped": True, "reason": "sem agent_id — só inbox"}
        return out

    from learning_agent.core import cursor_agent_bridge as bridge

    # Força a sessão do user_id a apontar para o agent do canal
    bridge._set_session(user_id, agent_id)  # noqa: SLF001
    prompt = (
        f"[Canal Cursor: {target.get('label') or target['name']}]\n"
        f"{message.strip()}"
    )
    result = bridge.consult(user_id, prompt, reset=False)
    out["consult"] = result
    out["ok"] = bool(result.get("success"))
    if not out["ok"]:
        out["error"] = result.get("error")
    return out


def format_targets_help() -> str:
    rows = list_targets()
    lines = [
        "Canais Cursor (não são abas do Composer — são sessões SDK nomeadas):",
        "",
        "/cursor targets — lista",
        "/cursor bind <nome> current — liga nome à sessão atual",
        "/cursor bind <nome> <agent_id> — liga a um agent_id",
        "/cursor unbind <nome>",
        "/cursor @<nome>: <mensagem> — notifica esse canal",
        "/cursor inbox <nome> — jobs pendentes",
        "",
        "Teatrinho (exemplo):",
        "1) /cursor oi  (cria sessão)",
        "2) /cursor bind teatrinho current",
        "3) Peça à Ravenna enviar o filme ao Debian e notificar @teatrinho",
    ]
    if not rows:
        lines.append("\nNenhum canal ainda.")
    else:
        lines.append("\nCanais:")
        for r in rows:
            aid = (r.get("agent_id") or "")[:12]
            lines.append(f"- {r['name']}: agent={aid}… | {r.get('label')}")
    return "\n".join(lines)
