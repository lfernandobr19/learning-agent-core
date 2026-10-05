"""Tests for remote-live SSH mirror on write."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from learning_agent.core import remote_live


def test_is_live_root_reads_meta(tmp_path: Path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / remote_live.META_FILENAME).write_text(
        json.dumps({"kind": "remote-live", "profile_id": "remote_app-teste"}),
        encoding="utf-8",
    )

    from learning_agent.core.workspace_roots import WorkspaceRootsError

    def fake_get_root_path(root_id: str) -> Path:
        if root_id == "test-root":
            return cache
        raise WorkspaceRootsError("missing", status_code=404)

    monkeypatch.setattr(
        "learning_agent.core.workspace_roots.get_root_path",
        fake_get_root_path,
    )
    assert remote_live.is_live_root("test-root") is True
    assert remote_live.is_live_root("other") is False


def test_mirror_after_local_write_skips_non_live(tmp_path: Path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / remote_live.META_FILENAME).write_text(
        json.dumps({"kind": "remote-cache", "profile_id": "remote_app-teste"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "learning_agent.core.workspace_roots.get_root_path",
        lambda root_id: cache,
    )
    assert remote_live.mirror_after_local_write("test-root", "remote_app/a.py", "x") is None


@patch("learning_agent.core.remote_live._open_paramiko_client")
def test_push_file_live(mock_client, tmp_path: Path):
    from learning_agent.core.remote_workspace import RemoteProfile

    sftp = MagicMock()
    remote_file = MagicMock()
    sftp.file.return_value.__enter__ = MagicMock(return_value=remote_file)
    sftp.file.return_value.__exit__ = MagicMock(return_value=False)
    client = MagicMock()
    client.open_sftp.return_value = sftp
    mock_client.return_value = client

    prof = RemoteProfile(
        id="remote_app-teste",
        host="<REMOTE_HOST>",
        port=2772,
        user="luis",
        remote_path="/home/luis/REMOTE_APP",
    )
    result = remote_live.push_file_live(prof, "remote_app/foo.py", "hello", password="secret")
    assert result["ok"] is True
    assert result["remote_path"] == "/home/luis/REMOTE_APP/remote_app/foo.py"
    remote_file.write.assert_called_once()
