"""Gateway "envia à Ravenna" (/v1) — banco de conhecimento por projeto (RemoteApp).

Os dois editores (Cursor do Luis + VS Code do colega) trabalham com os próprios
agentes em modo ASK (só conversa, sem editar arquivo). Quando uma ideia vira
decisão consolidada, o gesto explícito "envia à Ravenna" promove uma nota ao
banco de conhecimento do projeto (tag = project_id). A aplicação real de código
só acontece quando o Luis dá a ordem na IDE Ravenna (modo Agent) — nunca aqui.

Cada editor é identificado por um token Bearer (EDITOR_TOKENS).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from learning_agent.core import editor

router = APIRouter(prefix="/v1", tags=["remote_app-gateway"])


# ---------------------------------------------------------------------------
# Auth (Bearer token → pessoa)
# ---------------------------------------------------------------------------

def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def require_editor(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Dependência de auth aplicada apenas às rotas /v1/*."""
    token = _bearer_token(authorization)
    if not editor.is_auth_enabled():
        # Sem tokens cadastrados → gateway aberto (protegido por LAN/Tailscale).
        return {"user_id": "editor", "name": "editor", "token": token}
    identity = editor.resolve_token(token)
    if not identity:
        raise HTTPException(status_code=401, detail="Token inválido ou ausente")
    return {"user_id": identity["user_id"], "name": identity["name"], "token": token}


# ---------------------------------------------------------------------------
# Banco de conhecimento do projeto ("envia à Ravenna")
# ---------------------------------------------------------------------------

class EditorMessageIn(BaseModel):
    role: str = "user"
    content: str = ""


class EditorNoteRequest(BaseModel):
    title: str
    content: str
    messages: list[EditorMessageIn] | None = None


@router.post("/projects/{project_id}/notes")
def create_project_note(
    project_id: str,
    body: EditorNoteRequest,
    identity: dict[str, str] = Depends(require_editor),
) -> dict[str, Any]:
    """Gesto explícito: promove a ideia e anexa na conversa única do projeto."""
    author = identity.get("name") or identity.get("user_id") or ""
    result = editor.promote_project_note(
        project_id,
        body.title,
        body.content,
        author=author,
    )
    transcript = (
        [{"role": m.role, "content": m.content} for m in body.messages]
        if body.messages
        else None
    )
    conversation = editor.append_to_project_conversation(
        project_id,
        body.title,
        body.content,
        author=author,
        messages=transcript,
    )
    return {
        "ok": True,
        "project_id": editor.normalize_project_id(project_id),
        "note": result,
        "conversation_id": conversation["conversation_id"],
    }
