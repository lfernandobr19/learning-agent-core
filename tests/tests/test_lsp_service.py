"""Testes LSP proxy — completions e hover."""

from __future__ import annotations

from fastapi.testclient import TestClient

from learning_agent.api import app

client = TestClient(app)


def test_lsp_completion_python_keywords():
    r = client.post(
        "/api/lsp/completion",
        json={"language_id": "python", "path": "", "line": 1, "character": 1, "prefix": "d"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    labels = [i["label"] for i in data.get("items", [])]
    assert "def" in labels


def test_lsp_hover_returns_markdown():
    r = client.post(
        "/api/lsp/hover",
        json={"language_id": "python", "path": "learning_agent/config.py", "line": 1, "character": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert "contents" in data
