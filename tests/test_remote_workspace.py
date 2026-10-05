from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from learning_agent.core import remote_workspace as rw


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "remote-servers.json"
    cache = tmp_path / "cache"
    monkeypatch.setattr(rw, "PROFILES_PATH", store)
    monkeypatch.setattr(rw, "CACHE_BASE", cache)
    monkeypatch.setattr(rw, "LEGACY_PROFILE_PATH", tmp_path / "legacy.json")
    for key in (
        "REMOTE_SSH_HOST",
        "REMOTE_SSH_USER",
        "REMOTE_SSH_PORT",
        "REMOTE_SSH_IDENTITY",
        "REMOTE_SSH_ALIAS",
        "REMOTE_SSH_PATH",
        "remoteapp_SSH_HOST",
        "remoteapp_SSH_ALIAS",
        "remoteapp_REMOTE_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    return store


def test_load_profile_from_env(monkeypatch: pytest.MonkeyPatch, isolated_store: Path) -> None:
    monkeypatch.setenv("REMOTE_SSH_ALIAS", "vm-test")
    monkeypatch.setenv("REMOTE_SSH_PATH", "/srv/app")
    prof = rw.load_profile()
    assert prof.ssh_config_alias == "vm-test"
    assert prof.remote_path == "/srv/app"


def test_save_and_list_profiles(isolated_store: Path) -> None:
    prof = rw.RemoteProfile(label="App A", ssh_config_alias="vm-a", remote_path="/var/www/a")
    saved = rw.save_profile(prof)
    assert saved.id
    profiles = rw.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].label == "App A"


def test_test_connection_ok(monkeypatch: pytest.MonkeyPatch, isolated_store: Path) -> None:
    prof = rw.save_profile(
        rw.RemoteProfile(id="vm-a", label="App A", ssh_config_alias="vm-a", remote_path="/srv/app")
    )

    def fake_run(args, **kwargs):
        cmd = " ".join(args)
        proc = MagicMock()
        proc.returncode = 0
        if "RAVENNA_OK" in cmd:
            proc.stdout = "RAVENNA_OK\nvm-host\n/home/ubuntu\n"
            proc.stderr = ""
        elif "PATH_OK" in cmd:
            proc.stdout = "PATH_OK\n"
            proc.stderr = ""
        else:
            proc.stdout = "total 0\n"
            proc.stderr = ""
        return proc

    monkeypatch.setattr(rw.subprocess, "run", fake_run)
    result = rw.test_connection(prof)
    assert result["ok"] is True
    assert result["hostname"] == "vm-host"


def test_password_auth_probe_uses_openssh(monkeypatch: pytest.MonkeyPatch, isolated_store: Path) -> None:
    prof = rw.save_profile(
        rw.RemoteProfile(id="vm-o", label="O", host="203.0.113.4", user="root", port=22)
    )

    def fake_askpass(profile, remote_cmd, password, *, timeout=120):
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "RAVENNA_OK\nhost\n/home/root\n"
        proc.stderr = ""
        return proc

    monkeypatch.setattr(rw, "_run_ssh_with_password", fake_askpass)
    ok, host, pwd = rw._password_auth_probe(prof, password="secret")
    assert ok is True
    assert host == "host"
    assert pwd == "/home/root"


def test_apply_username_override_clears_alias(isolated_store: Path) -> None:
    prof = rw.save_profile(
        rw.RemoteProfile(
            id="alias-host",
            label="Alias",
            host="203.0.113.3",
            user="wrong",
            port=2772,
            ssh_config_alias="<REMOTE_HOST>",
        )
    )
    updated = rw._apply_username_override(prof, "luis_barbosa")
    assert updated.user == "luis_barbosa"
    assert updated.ssh_config_alias == ""
    assert rw._format_connect_identity(updated) == "luis_barbosa@203.0.113.3:2772"


def test_browse_needs_password_on_auth_fail(monkeypatch: pytest.MonkeyPatch, isolated_store: Path) -> None:
    prof = rw.save_profile(
        rw.RemoteProfile(
            id="vm-pwd",
            label="Pwd",
            host="203.0.113.1",
            user="ubuntu",
            port=22,
        )
    )

    def fake_run(args, **kwargs):
        proc = MagicMock()
        proc.returncode = 255
        proc.stdout = ""
        proc.stderr = "Permission denied (publickey,password)."
        return proc

    monkeypatch.setattr(rw.subprocess, "run", fake_run)
    result = rw.browse_remote_directory(profile_id=prof.id, path="~")
    assert result["ok"] is False
    assert result["needs_password"] is True


def test_browse_paramiko(monkeypatch: pytest.MonkeyPatch, isolated_store: Path) -> None:
    prof = rw.save_profile(
        rw.RemoteProfile(id="vm-p", label="P", host="203.0.113.2", user="root", port=22)
    )

    class FakeAttr:
        def __init__(self, name: str, mode: int) -> None:
            self.filename = name
            self.st_mode = mode

    class FakeSftp:
        def listdir_attr(self, path: str):
            assert path == "/home/root"
            return [
                FakeAttr("projeto", stat.S_IFDIR | 0o755),
                FakeAttr("readme.txt", stat.S_IFREG | 0o644),
            ]

        def close(self) -> None:
            return None

    class FakeClient:
        def exec_command(self, cmd: str):
            stdout = MagicMock()
            stdout.read.return_value = b"/home/root\n"
            return None, stdout, MagicMock()

        def open_sftp(self):
            return FakeSftp()

        def close(self) -> None:
            return None

    def fake_askpass_fail(profile, remote_cmd, password, *, timeout=120):
        proc = MagicMock()
        proc.returncode = 255
        proc.stdout = ""
        proc.stderr = "Permission denied (publickey,password)."
        return proc

    monkeypatch.setattr(rw, "_run_ssh_with_password", fake_askpass_fail)
    monkeypatch.setattr(rw, "_open_paramiko_client", lambda *a, **k: FakeClient())
    result = rw.browse_remote_directory(profile_id=prof.id, path="~", password="secret")
    assert result["ok"] is True
    assert result["path"] == "/home/root"
    names = [e["name"] for e in result["entries"]]
    assert "projeto" in names
    assert "readme.txt" in names
