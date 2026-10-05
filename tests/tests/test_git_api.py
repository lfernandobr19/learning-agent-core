"""Testes — Git integrado (Fase 6)."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.git_ops import GitError, commit_changes, get_diff, get_status


@pytest.fixture
def git_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(tmp_path))
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
    return tmp_path


def test_status_clean_sandbox(git_sandbox):
    st = get_status()
    assert st["branch"] in {"main", "master"}
    assert st["clean"] is True
    assert st["counts"]["staged"] == 0


def test_diff_and_commit(git_sandbox):
    (git_sandbox / "hello.txt").write_text("v2\n", encoding="utf-8")
    st = get_status()
    assert st["clean"] is False
    assert any(f["path"] == "hello.txt" for f in st["unstaged"])

    diff = get_diff("hello.txt")
    assert "v2" in diff["diff"] or "hello.txt" in diff["diff"]

    result = commit_changes("feat: update hello", ["hello.txt"])
    assert result["committed"] is True
    assert "hello.txt" in result["paths"]

    after = get_status()
    assert after["clean"] is True


def test_not_a_repo_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(tmp_path))
    try:
        get_status()
        assert False, "expected GitError"
    except GitError as exc:
        assert exc.status_code == 404


def test_api_git_endpoints(git_sandbox):
    (git_sandbox / "note.txt").write_text("new\n", encoding="utf-8")
    with TestClient(app) as client:
        st = client.get("/api/git/status")
        assert st.status_code == 200
        body = st.json()
        assert body["clean"] is False

        diff = client.get("/api/git/diff", params={"path": "note.txt"})
        assert diff.status_code == 200
        assert "diff" in diff.json()

        bad = client.post("/api/git/commit", json={"message": "", "paths": ["note.txt"]})
        assert bad.status_code in (400, 422)

        ok = client.post(
            "/api/git/commit",
            json={"message": "test: add note", "paths": ["note.txt"]},
        )
        assert ok.status_code == 200
        assert ok.json()["committed"] is True
