"""Testes — git multi-root."""

from __future__ import annotations

import subprocess

import pytest

from learning_agent.core.git_ops import GitError, get_git_summary, get_status, init_repo


@pytest.fixture
def git_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(tmp_path))
    from learning_agent.core import workspace_roots

    monkeypatch.setattr(workspace_roots, "REGISTRY_PATH", tmp_path / "roots.json")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    root_id = workspace_roots.list_roots()[0]["id"]
    return root_id, tmp_path


def test_git_status_with_root_id(git_sandbox):
    root_id, _ = git_sandbox
    st = get_status(root_id)
    assert st["clean"] is True


def test_git_summary_lists_roots(git_sandbox):
    summary = get_git_summary()
    assert any(row["root_id"] for row in summary["summaries"])


def test_git_init_rejects_existing_repo(git_sandbox):
    root_id, _ = git_sandbox
    with pytest.raises(GitError):
        init_repo(root_id)
