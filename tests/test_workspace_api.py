"""Testes do explorer — workspace seguro (multi-root)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.workspace import (
    WorkspaceError,
    list_directory,
    read_file,
    resolve_path,
    write_file,
)
from learning_agent.core.workspace_roots import add_folder_root


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path_factory, monkeypatch):
    """Isola o registry de workspaces em um arquivo temporário por teste."""
    import learning_agent.core.workspace_roots as wr

    reg_dir = tmp_path_factory.mktemp("registry")
    monkeypatch.setattr(wr, "REGISTRY_PATH", reg_dir / "roots.json")


def _seed_root(tmp_path, filename: str = "sample.txt") -> str:
    (tmp_path / filename).write_text("x\n", encoding="utf-8")
    return add_folder_root(str(tmp_path))["id"]


def test_resolve_path_blocks_traversal():
    try:
        resolve_path("../etc/passwd")
        assert False, "expected WorkspaceError"
    except WorkspaceError as exc:
        assert exc.status_code == 400


def test_list_directory_root(tmp_path):
    root_id = _seed_root(tmp_path, "sample.txt")
    data = list_directory(root_id)
    assert "entries" in data
    assert any(e["name"] == "sample.txt" for e in data["entries"])


def test_read_readme(tmp_path):
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    root_id = add_folder_root(str(tmp_path))["id"]
    data = read_file(f"{root_id}/README.md")
    assert "content" in data
    assert data["content"] == "hello\n"


def test_api_files_list():
    with TestClient(app) as client:
        r = client.get("/api/files")
        assert r.status_code == 200
        assert "entries" in r.json()


def test_api_files_content(tmp_path):
    (tmp_path / "README.md").write_text("api\n", encoding="utf-8")
    root_id = add_folder_root(str(tmp_path))["id"]
    with TestClient(app) as client:
        r = client.get("/api/files/content", params={"path": f"{root_id}/README.md"})
        assert r.status_code == 200
        assert r.json()["name"] == "README.md"


def test_api_files_traversal_400():
    with TestClient(app) as client:
        r = client.get("/api/files/content", params={"path": "../../Windows/System.ini"})
        assert r.status_code in (400, 403, 404)


def test_write_file_roundtrip(tmp_path):
    root_id = add_folder_root(str(tmp_path))["id"]
    scratch = f"{root_id}/_scratch_phase2.txt"
    try:
        write_file(scratch, "ravenna phase 2\n")
        data = read_file(scratch)
        assert data["content"] == "ravenna phase 2\n"
        assert data["writable"] is True
    finally:
        resolve_path(scratch).unlink(missing_ok=True)


def test_api_put_file_content(tmp_path):
    root_id = add_folder_root(str(tmp_path))["id"]
    scratch = f"{root_id}/_scratch_api_phase2.txt"
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
