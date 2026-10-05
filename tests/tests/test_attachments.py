"""Testes — upload de anexos (Fase 4)."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.attachments import AttachmentError, list_attachments, save_attachment


def test_save_attachment_text():
    result = save_attachment("test-phase4.md", b"# hello ravenna\n")
    assert result["indexed"] is True
    assert result["filename"] == "test-phase4.md"
    listed = list_attachments()
    assert any(x["id"] == result["id"] for x in listed)


def test_reject_bad_extension():
    try:
        save_attachment("virus.exe", b"bad")
        assert False
    except AttachmentError as exc:
        assert exc.status_code == 415


def test_api_upload():
    with TestClient(app) as client:
        r = client.post(
            "/api/attachments",
            files={"file": ("api-test.txt", io.BytesIO(b"api upload"), "text/plain")},
        )
        assert r.status_code == 200
        assert r.json()["indexed"] is True
        g = client.get("/api/attachments")
        assert g.status_code == 200
        assert len(g.json()["attachments"]) >= 1
