"""Catalisador RemoteApp — identidade de editor e conhecimento por projeto.

Dois editores externos (Cursor do Luis + VS Code do colega) trabalham com os
próprios agentes em modo ASK; quando algo vira decisão consolidada, o gesto
"envia à Ravenna" promove uma nota ao banco de conhecimento do projeto (tag).
Este módulo concentra a lógica pura (sem FastAPI): resolução de token (pessoa),
namespace de projeto e promoção/busca de conhecimento compartilhado.
"""

from __future__ import annotations

import json
from typing import Any

from learning_agent.config import (
    EDITOR_LOCKED_ENGINE,
    EDITOR_PROJECT,
    EDITOR_TOKENS,
    EDITOR_GATEWAY_URL,
    EDITOR_TOKEN,
)
from learning_agent.core import knowledge


def is_auth_enabled() -> bool:
    """Auth obrigatória só quando há tokens cadastrados (env EDITOR_TOKENS)."""
    return bool(EDITOR_TOKENS)


def resolve_token(token: str | None) -> dict[str, str] | None:
    """Retorna {user_id, name} se o token for conhecido, senão None."""
    token = (token or "").strip()
    if not token:
        return None
    return EDITOR_TOKENS.get(token)


def locked_engine() -> str:
    """Motor travado para o gateway (ignora o que o cliente pedir)."""
    return EDITOR_LOCKED_ENGINE


def normalize_project_id(project_id: str | None) -> str:
    pid = (project_id or EDITOR_PROJECT).strip().lower()
    return pid or EDITOR_PROJECT


def project_conversation_id(project_id: str | None = None) -> str:
    """Id estável da conversa única do projeto na IDE Ravenna."""
    return f"conv-project-{normalize_project_id(project_id)}"


def _workspace_binding(project_id: str) -> tuple[str, str, list[str]]:
    """Amarra a conversa ao root aberto na IDE (ex.: id `remote_app`)."""
    pid = normalize_project_id(project_id)
    name = "REMOTE_APP" if pid == "remote_app" else pid
    project_root = ""
    root_ids: list[str] = []
    try:
        from learning_agent.core.workspace_roots import list_roots

        for root in list_roots():
            rid = str(root.get("id") or "")
            rname = str(root.get("name") or "")
            rpath = str(root.get("path") or "").replace("\\", "/").rstrip("/")
            if (
                rid.lower() == pid
                or rname.lower() == pid
                or rpath.lower().endswith(f"/{pid}")
                or rpath.lower().endswith(f"/{name.lower()}")
            ):
                root_ids = [rid]
                project_root = str(root.get("path") or "")
                name = rname or name
                break
    except Exception:
        pass
    if not root_ids:
        root_ids = [pid]
    return name, project_root, root_ids


def ensure_project_conversation(project_id: str | None = None) -> dict[str, Any]:
    """Garante a conversa única do projeto, visível ao abrir esse workspace na IDE."""
    from learning_agent.core import chat
    from learning_agent import db

    pid = normalize_project_id(project_id)
    cid = project_conversation_id(pid)
    name, project_root, root_ids = _workspace_binding(pid)
    title = f"{name} — memória das IDEs"
    db.init_db()
    now = db._utcnow()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM chat_conversations WHERE id = ?",
            (cid,),
        ).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO chat_conversations (
                    id, channel, title, created_at, updated_at,
                    project_name, project_root, workspace_root_ids, archived
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    cid,
                    chat.IDE_CHANNEL,
                    title,
                    now,
                    now,
                    name,
                    project_root,
                    json.dumps(root_ids),
                ),
            )
    chat.update_conversation(
        cid,
        title=title,
        project_name=name,
        project_root=project_root,
        workspace_root_ids=root_ids,
    )
    try:
        chat.archive_conversation(cid, archived=False)
    except Exception:
        pass
    with db.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE channel = ? AND user_id = ?",
            (chat.IDE_CHANNEL, cid),
        ).fetchone()
    if not count or int(count["n"] or 0) == 0:
        chat._save_message(
            chat.IDE_CHANNEL,
            cid,
            "assistant",
            (
                f"Esta é a conversa única do projeto {name}. "
                "O que chegar do Cursor e do VS Code entra aqui, sempre neste mesmo fio."
            ),
        )
        chat.touch_conversation(cid)
    return {
        "id": cid,
        "title": title,
        "project_name": name,
        "project_root": project_root,
        "workspace_root_ids": root_ids,
    }


def append_to_project_conversation(
    project_id: str,
    title: str,
    content: str,
    *,
    author: str = "",
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Grava o gesto (ou um trecho de conversa) sempre na mesma conversa do projeto."""
    from learning_agent.core import chat

    conv = ensure_project_conversation(project_id)
    cid = str(conv["id"])
    who = (author or "editor").strip() or "editor"
    chunks: list[tuple[str, str]] = []
    if messages:
        for item in messages:
            role = str(item.get("role") or "user").strip().lower()
            text = str(item.get("content") or "").strip()
            if not text:
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            if role == "user":
                text = f"[{who}] {text}"
            chunks.append((role, text[:12000]))
    else:
        body = (content or "").strip()
        head = (title or "").strip()
        text = f"[{who}] {head}\n\n{body}".strip() if head else f"[{who}] {body}"
        if text:
            chunks.append(("user", text[:12000]))

    for role, text in chunks:
        chat._save_message(chat.IDE_CHANNEL, cid, role, text)
    if chunks:
        chat.touch_conversation(cid)
    return {"conversation_id": cid, "appended": len(chunks)}


def promote_project_note(
    project_id: str,
    title: str,
    content: str,
    *,
    author: str = "",
) -> dict[str, Any]:
    """Promove uma ideia consolidada ao banco de conhecimento do projeto.

    Uso: gesto explícito "envia à Ravenna" — só entra o que for consolidado.
    """
    pid = normalize_project_id(project_id)
    tags = [pid]
    if author:
        tags.append(f"author:{author}")
    return knowledge.add_note(title, content, tags)


def _self_token() -> str:
    """Token do editor que dispara o gesto: EDITOR_TOKEN ou o token do Luis.

    A tool MCP `send_to_ravenna` grava no servidor via HTTP. O token vem de
    EDITOR_TOKEN (explícito no .env) ou, como fallback, do token cujo user_id é
    "luis" em EDITOR_TOKENS (cobre o caso do MCP rodando na própria Ravenna).
    """
    if EDITOR_TOKEN:
        return EDITOR_TOKEN
    for tok, meta in EDITOR_TOKENS.items():
        if str(meta.get("user_id") or "").lower() == "luis":
            return tok
    return ""


def promote_project_note_via_http(
    project_id: str,
    title: str,
    content: str,
    *,
    author: str = "",
) -> dict[str, Any]:
    """Promove nota via gateway HTTP — grava no banco do servidor (qualquer máquina).

    Usado pela tool MCP send_to_ravenna para que o gesto sempre caia na memória
    da Ravenna (servidor), e não no banco local do editor.
    """
    import json
    import urllib.error
    import urllib.request

    pid = normalize_project_id(project_id)
    url = f"{EDITOR_GATEWAY_URL}/v1/projects/{pid}/notes"
    body = json.dumps({"title": title, "content": content}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = _self_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {exc.code}", "detail": detail[:500]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def search_project(
    query: str,
    project_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Busca conhecimento restrito ao projeto (filtra pela tag do projeto)."""
    pid = normalize_project_id(project_id)
    # Pede mais do que o necessário e filtra por tag, pois o RAG não filtra por tag.
    results = knowledge.search(query, limit=max(limit * 4, 20))
    matched: list[dict[str, Any]] = []
    for item in results:
        meta = item.get("metadata") or {}
        tags = str(meta.get("tags") or "")
        tag_set = {t.strip() for t in tags.split(",") if t.strip()}
        if pid in tag_set:
            matched.append(item)
            if len(matched) >= limit:
                break
    return matched


def project_context_for(
    query: str,
    project_id: str | None = None,
    limit: int = 4,
) -> str:
    """Contexto textual do projeto a injetar no system prompt do gateway."""
    try:
        notes = search_project(query, project_id, limit)
    except Exception:
        return ""
    if not notes:
        return ""
    lines: list[str] = []
    for note in notes:
        meta = note.get("metadata") or {}
        title = str(meta.get("title") or "").strip()
        content = str(note.get("content") or "").strip()
        if title and content:
            lines.append(f"- {title}: {content}")
        elif content:
            lines.append(f"- {content}")
    if not lines:
        return ""
    return "Conhecimento consolidado do projeto:\n" + "\n".join(lines)
