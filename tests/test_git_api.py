"""Testes — Git integrado (Fase 6), API multi-root."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.git_ops import GitError, commit_changes, get_diff, get_status
from learning_agent.core.workspace_roots import add_folder_root


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path_factory, monkeypatch):
    """Isola o registry de workspaces em um arquivo temporário por teste.

    Usa tmp_path_factory (diretório próprio) para não poluir o sandbox git,
    que também usa tmp_path — um registry escrito dentro do sandbox criaria
    um arquivo não rastreado e tornaria `git status` sujo.
    """
    import learning_agent.core.workspace_roots as wr

    reg_dir = tmp_path_factory.mktemp("registry")
    monkeypatch.setattr(wr, "REGISTRY_PATH", reg_dir / "roots.json")


@pytest.fixture
def git_sandbox(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ravenna@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Ravenna Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "hello.txt"
    seed.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    root_id = add_folder_root(str(tmp_path))["id"]
    return tmp_path, root_id


def _ref(root_id: str, name: str) -> str:
    return f"{root_id}/{name}"


def test_status_clean_sandbox(git_sandbox):
    _tmp, root_id = git_sandbox
    st = get_status(root_id)
    assert st["branch"] in {"main", "master"}
    assert st["clean"] is True
    assert st["counts"]["staged"] == 0


def test_diff_and_commit(git_sandbox):
    tmp_path, root_id = git_sandbox
    (tmp_path / "hello.txt").write_text("v2\n", encoding="utf-8")
    st = get_status(root_id)
    assert st["clean"] is False
    assert any(f["path"] == "hello.txt" for f in st["unstaged"])

    diff = get_diff(_ref(root_id, "hello.txt"), root_id=root_id)
    assert "v2" in diff["diff"] or "hello.txt" in diff["diff"]

    result = commit_changes("feat: update hello", [_ref(root_id, "hello.txt")], root_id=root_id)
    assert result["committed"] is True
    assert "hello.txt" in result["paths"]

    after = get_status(root_id)
    assert after["clean"] is True


def test_not_a_repo_raises(tmp_path):
    root_id = add_folder_root(str(tmp_path))["id"]
    try:
        get_status(root_id)
        assert False, "expected GitError"
    except GitError as exc:
        assert exc.status_code == 404


def test_api_git_endpoints(git_sandbox):
    tmp_path, root_id = git_sandbox
    (tmp_path / "note.txt").write_text("new\n", encoding="utf-8")
    with TestClient(app) as client:
        st = client.get("/api/git/status", params={"root_id": root_id})
        assert st.status_code == 200
        body = st.json()
        assert body["clean"] is False

        diff = client.get(
            "/api/git/diff",
            params={"path": _ref(root_id, "note.txt"), "root_id": root_id},
        )
        assert diff.status_code == 200
        assert "diff" in diff.json()

        bad = client.post(
            "/api/git/commit",
            params={"root_id": root_id},
            json={"message": "", "paths": [_ref(root_id, "note.txt")]},
        )
        assert bad.status_code in (400, 422)

        ok = client.post(
            "/api/git/commit",
            params={"root_id": root_id},
            json={"message": "test: add note", "paths": [_ref(root_id, "note.txt")]},
        )
        assert ok.status_code == 200
        assert ok.json()["committed"] is True
