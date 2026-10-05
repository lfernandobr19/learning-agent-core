"""Testes do explorer — workspace seguro."""

from __future__ import annotations

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.workspace import (
    WorkspaceError,
    list_directory,
    read_file,
    resolve_path,
    write_file,
)


def test_resolve_path_blocks_traversal():
    try:
        resolve_path("../etc/passwd")
        assert False, "expected WorkspaceError"
    except WorkspaceError as exc:
        assert exc.status_code == 400


def test_list_directory_root():
    data = list_directory("")
    assert "entries" in data
    assert any(e["name"] == "learning_agent" for e in data["entries"])


def test_read_readme():
    data = read_file("README.md")
    assert "content" in data
    assert len(data["content"]) > 0


def test_api_files_list():
    with TestClient(app) as client:
        r = client.get("/api/files")
        assert r.status_code == 200
        assert "entries" in r.json()


def test_api_files_content():
    with TestClient(app) as client:
        r = client.get("/api/files/content", params={"path": "README.md"})
        assert r.status_code == 200
        assert r.json()["name"] == "README.md"


def test_api_files_traversal_400():
    with TestClient(app) as client:
        r = client.get("/api/files/content", params={"path": "../../Windows/System.ini"})
        assert r.status_code in (400, 403, 404)


def test_write_file_roundtrip():
    scratch = "tests/_scratch_phase2.txt"
    try:
        write_file(scratch, "ravenna phase 2\n")
        data = read_file(scratch)
        assert data["content"] == "ravenna phase 2\n"
        assert data["writable"] is True
    finally:
        resolve_path(scratch).unlink(missing_ok=True)


def test_api_put_file_content():
    scratch = "tests/_scratch_api_phase2.txt"
    with TestClient(app) as client:
        try:
            r = client.put(
                "/api/files/content",
                json={"path": scratch, "content": "via api\n"},
            )
            assert r.status_code == 200
            assert r.json()["saved"] is True
            g = client.get("/api/files/content", params={"path": scratch})
            assert g.json()["content"] == "via api\n"
        finally:
            resolve_path(scratch).unlink(missing_ok=True)
