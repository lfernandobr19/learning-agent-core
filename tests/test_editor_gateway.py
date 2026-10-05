"""Testes — gateway "envia à Ravenna" (/v1) (Catalisador RemoteApp).

Cobertura por fase:
- Fase 0: auth por token + identidade de projeto + regressão /api/* e /health.
- Fase 2: promoção de nota por projeto ("envia à Ravenna") + busca filtrada por tag.

(Fase 1 — gateway de chat OpenAI-compatível — foi removida: os editores usam os
próprios agentes em modo ASK e só promovem notas consolidadas.)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core import editor

TOKENS = {"tok-a": {"user_id": "luis", "name": "Luis"}}


def _enable_auth(monkeypatch, tokens):
    monkeypatch.setattr(editor, "EDITOR_TOKENS", tokens)


# ---------------------------------------------------------------------------
# Fase 0 — auth + identidade de projeto
# ---------------------------------------------------------------------------

def test_health_and_api_routes_unaffected_by_editor_auth(monkeypatch):
    _enable_auth(monkeypatch, TOKENS)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/mcp/status").status_code == 200
        assert client.get("/progress").status_code == 200


def test_v1_requires_valid_token(monkeypatch):
    _enable_auth(monkeypatch, TOKENS)
    with TestClient(app) as client:
        payload = {"title": "t", "content": "c"}
        assert client.post("/v1/projects/remote_app/notes", json=payload).status_code == 401
        assert (
            client.post(
                "/v1/projects/remote_app/notes",
                json=payload,
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )


def test_v1_open_when_no_tokens(monkeypatch):
    _enable_auth(monkeypatch, {})
    monkeypatch.setattr(
        "learning_agent.core.editor.knowledge.add_note",
        lambda *a, **k: {"id": 1},
    )
    with TestClient(app) as client:
        r = client.post(
            "/v1/projects/remote_app/notes", json={"title": "t", "content": "c"}
        )
        assert r.status_code == 200


def test_resolve_token_and_project(monkeypatch):
    _enable_auth(monkeypatch, TOKENS)
    assert editor.resolve_token("tok-a")["user_id"] == "luis"
    assert editor.resolve_token(None) is None
    assert editor.normalize_project_id("  RemoteApp ") == "remote_app"
    assert editor.normalize_project_id(None) == "remote_app"


# ---------------------------------------------------------------------------
# Fase 2 — banco de conhecimento do projeto
# ---------------------------------------------------------------------------

def test_promote_note_endpoint(monkeypatch):
    _enable_auth(monkeypatch, TOKENS)
    calls: dict = {}

    def fake_add_note(title, content, tags):
        calls["title"] = title
        calls["content"] = content
        calls["tags"] = tags
        return {"id": 1, "title": title, "content": content, "tags": tags}

    monkeypatch.setattr("learning_agent.core.editor.knowledge.add_note", fake_add_note)
    with TestClient(app) as client:
        r = client.post(
            "/v1/projects/remote_app/notes",
            headers={"Authorization": "Bearer tok-a"},
            json={"title": "Decisão X", "content": "Usar FastAPI no core"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["project_id"] == "remote_app"
        assert body["conversation_id"] == "conv-project-remote_app"

    assert calls["title"] == "Decisão X"
    assert "remote_app" in calls["tags"]
    assert "author:Luis" in calls["tags"]


def test_project_context_filters_by_tag(monkeypatch):
    fake_results = [
        {
            "id": "note:1",
            "content": "Ideia do remote_app",
            "metadata": {"title": "N1", "tags": "remote_app,author:Luis"},
            "distance": 0.1,
        },
        {
            "id": "note:2",
            "content": "outro projeto",
            "metadata": {"title": "N2", "tags": "outro"},
            "distance": 0.2,
        },
    ]
    monkeypatch.setattr(
        "learning_agent.core.editor.knowledge.search", lambda q, limit=5: fake_results
    )
    ctx = editor.project_context_for("ideia", "remote_app")
    assert "N1" in ctx
    assert "N2" not in ctx
    assert editor.search_project("ideia", "remote_app")[0]["metadata"]["title"] == "N1"
