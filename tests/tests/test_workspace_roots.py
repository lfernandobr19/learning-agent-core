"""Testes multi-root workspace."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.workspace import list_directory, read_file, write_file
from learning_agent.core.workspace_roots import (
    REGISTRY_PATH,
    WorkspaceRootsError,
    add_folder_root,
    canonical_workspace_ref,
    discover_git_repos,
    list_roots,
    remove_root,
)


@pytest.fixture()
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    primary = tmp_path / "primary"
    secondary = tmp_path / "other"
    primary.mkdir()
    secondary.mkdir()
    (primary / "README.md").write_text("primary\n", encoding="utf-8")
    (secondary / "app.txt").write_text("other\n", encoding="utf-8")

    registry = tmp_path / "ide-workspace-roots.json"
    monkeypatch.setattr("learning_agent.core.workspace_roots.REGISTRY_PATH", registry)
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(primary))

    data = {
        "version": 1,
        "primary_id": "primary",
        "roots": [
            {"id": "primary", "name": "primary", "path": str(primary), "kind": "primary", "git": False},
            {"id": "other", "name": "other", "path": str(secondary), "kind": "folder", "git": False},
        ],
    }
    registry.write_text(__import__("json").dumps(data), encoding="utf-8")
    yield primary, secondary, registry


def test_list_directory_multi_root(isolated_registry):
    data = list_directory("")
    assert data["multi_root"] is True
    assert any(e["path"] == "other" and e["type"] == "root" for e in data["entries"])


def test_read_file_with_root_prefix(isolated_registry):
    _primary, secondary, _registry = isolated_registry
    data = read_file("other/app.txt")
    assert data["content"] == "other\n"
    assert data["root_id"] == "other"


def test_write_file_with_root_prefix(isolated_registry):
    data = write_file("other/new.txt", "hello\n")
    assert data["path"] == "other/new.txt"
    assert read_file("other/new.txt")["content"] == "hello\n"


def test_add_and_remove_folder_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registry = tmp_path / "roots.json"
    primary = tmp_path / "main"
    extra = tmp_path / "extra"
    primary.mkdir()
    extra.mkdir()
    monkeypatch.setattr("learning_agent.core.workspace_roots.REGISTRY_PATH", registry)
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(primary))

    root = add_folder_root(str(extra), name="extra")
    assert root["id"] == "extra"
    assert len(list_roots()) >= 2

    remove_root(root["id"])
    assert all(r["id"] != "extra" for r in list_roots())


def test_api_workspace_roots(isolated_registry):
    with TestClient(app) as client:
        r = client.get("/api/workspace/roots")
        assert r.status_code == 200
        body = r.json()
        assert len(body["roots"]) >= 2

        r2 = client.get("/api/files", params={"path": "other"})
        assert r2.status_code == 200
        assert "entries" in r2.json()


def test_discover_skips_attached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    parent = tmp_path / "parent"
    attached = parent / "attached"
    free = parent / "free"
    parent.mkdir()
    attached.mkdir()
    free.mkdir()
    (attached / ".git").mkdir()
    (free / ".git").mkdir()

    registry = tmp_path / "roots.json"
    monkeypatch.setattr("learning_agent.core.workspace_roots.REGISTRY_PATH", registry)
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(attached))

    repos = discover_git_repos(str(parent))
    names = {r["name"] for r in repos}
    assert "free" in names
    assert "attached" not in names


def test_canonical_workspace_ref_maps_remote_cache_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import json

    project = tmp_path / "learning-agent"
    remote_app = project / "data" / "remote-workspaces" / "remote_app-teste"
    remote_app.mkdir(parents=True)
    registry = project / "data" / "ide-workspace-roots.json"
    data = {
        "version": 1,
        "primary_id": "pc-workspace",
        "roots": [
            {"id": "pc-workspace", "name": "PC", "path": str(project / "pc"), "kind": "primary", "git": False},
            {
                "id": "luis-132-255-110-213",
                "name": "remote_app",
                "path": str(remote_app),
                "kind": "remote-cache",
                "git": False,
            },
        ],
    }
    registry.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("learning_agent.config.PROJECT_ROOT", project)
    monkeypatch.setattr("learning_agent.core.workspace_roots.PROJECT_ROOT", project)
    monkeypatch.setattr("learning_agent.core.workspace_roots.REGISTRY_PATH", registry)

    assert canonical_workspace_ref("data/remote-workspaces/remote_app-teste") == "luis-132-255-110-213"
    assert (
        canonical_workspace_ref("data/remote-workspaces/remote_app-teste/remote_app/routes.py")
        == "luis-132-255-110-213/remote_app/routes.py"
    )
    assert canonical_workspace_ref("luis-132-255-110-213/remote_app/routes.py") == "luis-132-255-110-213/remote_app/routes.py"


def test_browse_local_directory(isolated_registry, monkeypatch: pytest.MonkeyPatch):
    from learning_agent.core.workspace_roots import browse_local_directory

    primary, secondary, _registry = isolated_registry
    monkeypatch.setattr(
        "learning_agent.core.workspace_roots._allowed_browse_roots",
        lambda: (primary.resolve(), secondary.resolve()),
    )

    data = browse_local_directory(str(primary))
    assert data["ok"] is True
    assert data["path"] == str(primary.resolve())
    names = {e["name"] for e in data["entries"]}
    assert "README.md" in names or any(e["kind"] == "dir" for e in data["entries"])


def test_api_browse_workspace_roots(isolated_registry, monkeypatch: pytest.MonkeyPatch):
    primary, secondary, _registry = isolated_registry
    monkeypatch.setattr(
        "learning_agent.core.workspace_roots._allowed_browse_roots",
        lambda: (primary.resolve(), secondary.resolve()),
    )

    with TestClient(app) as client:
        r = client.get("/api/workspace/roots/browse", params={"path": str(primary)})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["path"] == str(primary.resolve())
