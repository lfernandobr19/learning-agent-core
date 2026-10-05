"""Edição remota ao vivo — gravações no cache espelham no servidor via SFTP (estilo Cursor SSH)."""

from __future__ import annotations

import json
import os
import posixpath
import stat
from io import BytesIO
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR
from learning_agent.core.remote_workspace import (
    RemoteProfile,
    RemoteWorkspaceError,
    _open_paramiko_client,
    _paramiko_auth_ok,
    load_profile,
)

SESSION_DIR = DATA_DIR / "remote-sessions"
META_FILENAME = ".ravenna-remote.json"


class RemoteLiveError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _session_path(profile_id: str) -> Path:
    safe = profile_id.replace("/", "_").replace("\\", "_")
    return SESSION_DIR / f"{safe}.json"


def save_session_password(profile_id: str, password: str) -> None:
    if not password.strip():
        return
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(profile_id)
    path.write_text(json.dumps({"password": password}, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_session_password(profile_id: str) -> None:
    _session_path(profile_id).unlink(missing_ok=True)


def load_session_password(profile_id: str) -> str:
    path = _session_path(profile_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pwd = data.get("password")
            if isinstance(pwd, str) and pwd.strip():
                return pwd.strip()
        except (OSError, json.JSONDecodeError):
            pass
    if profile_id == "remote_app-teste":
        return os.environ.get("remoteapp_SSH_PASSWORD", "").strip()
    return os.environ.get("REMOTE_SSH_PASSWORD", "").strip()


def read_cache_meta(cache_path: Path) -> dict[str, Any] | None:
    meta_file = cache_path / META_FILENAME
    if not meta_file.is_file():
        return None
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def meta_for_root(root_id: str) -> dict[str, Any] | None:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, get_root_path

    try:
        cache = get_root_path(root_id)
    except WorkspaceRootsError:
        return None
    return read_cache_meta(cache)


def is_live_root(root_id: str) -> bool:
    meta = meta_for_root(root_id)
    return bool(meta and meta.get("kind") == "remote-live")


def _resolve_password(prof: RemoteProfile) -> str:
    pwd = load_session_password(prof.id)
    if pwd:
        return pwd
    ok, _, _ = _paramiko_auth_ok(prof)
    if ok:
        return ""
    raise RemoteLiveError(
        "SSH sem credencial — reconecte pelo diálogo Connect SSH (senha) ou configure chave.",
        status_code=401,
    )


def _remote_file_path(prof: RemoteProfile, inner_path: str) -> str:
    base = (prof.remote_path or "").rstrip("/")
    rel = inner_path.replace("\\", "/").strip("/")
    if not base:
        raise RemoteLiveError("Caminho remoto do perfil não configurado", status_code=400)
    return posixpath.join(base, rel) if rel else base


def _sftp_makedirs(sftp: Any, remote_dir: str) -> None:
    remote_dir = remote_dir.replace("\\", "/")
    if not remote_dir or remote_dir in {"/", "."}:
        return
    is_abs = remote_dir.startswith("/")
    parts = [p for p in remote_dir.split("/") if p]
    current = "/" if is_abs else ""
    for part in parts:
        current = f"{current}/{part}" if current not in {"", "/"} else (f"/{part}" if is_abs else part)
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def push_file_live(
    prof: RemoteProfile,
    inner_path: str,
    content: str,
    *,
    password: str | None = None,
) -> dict[str, Any]:
    pwd = (password or load_session_password(prof.id)).strip()
    remote_path = _remote_file_path(prof, inner_path)
    remote_dir = posixpath.dirname(remote_path)
    payload = content.encode("utf-8")

    client = _open_paramiko_client(prof, password=pwd, timeout=30)
    try:
        sftp = client.open_sftp()
        try:
            _sftp_makedirs(sftp, remote_dir)
            with sftp.file(remote_path, "wb") as remote_file:
                remote_file.write(payload)
        finally:
            sftp.close()
    finally:
        client.close()

    return {
        "ok": True,
        "remote_path": remote_path,
        "bytes": len(payload),
        "profile_id": prof.id,
    }


def mirror_after_local_write(root_id: str, inner_path: str, content: str) -> dict[str, Any] | None:
    meta = meta_for_root(root_id)
    if not meta or meta.get("kind") != "remote-live":
        return None

    profile_id = str(meta.get("profile_id") or "").strip()
    if not profile_id:
        raise RemoteLiveError("Meta remote-live sem profile_id", status_code=500)

    prof = load_profile(profile_id)
    try:
        return push_file_live(prof, inner_path, content)
    except RemoteWorkspaceError as exc:
        raise RemoteLiveError(exc.message, status_code=exc.status_code) from exc
    except Exception as exc:
        raise RemoteLiveError(str(exc), status_code=502) from exc


def enable_live_for_profile(prof: RemoteProfile, *, password: str = "") -> None:
    if password.strip():
        save_session_password(prof.id, password)
    meta_path = prof.cache_path() / META_FILENAME
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    meta.update(
        {
            "kind": "remote-live",
            "profile_id": prof.id,
            "profile": prof.sanitized(),
            "remote_path": prof.remote_path,
            "display_target": prof.display_target(),
            "live_enabled_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        }
    )
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    _mark_registry_kind(prof.cache_path(), "remote-live")


def _mark_registry_kind(cache_path: Path, kind: str) -> None:
    from learning_agent.core.workspace_roots import REGISTRY_PATH, list_roots

    resolved = cache_path.resolve()
    if not REGISTRY_PATH.is_file():
        return
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for root in data.get("roots", []):
        try:
            if Path(root.get("path", "")).resolve() == resolved:
                root["kind"] = kind
                root["remote_profile_id"] = root.get("remote_profile_id")
                break
        except OSError:
            continue
    else:
        for root in list_roots():
            if Path(root["path"]).resolve() == resolved:
                for item in data.get("roots", []):
                    if item.get("id") == root["id"]:
                        item["kind"] = kind
                        break
                break
    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def probe_live_connection(root_id: str) -> dict[str, Any]:
    meta = meta_for_root(root_id)
    if not meta or meta.get("kind") != "remote-live":
        return {"ok": False, "live": False, "reason": "not remote-live"}
    profile_id = str(meta.get("profile_id") or "")
    prof = load_profile(profile_id)
    pwd = load_session_password(prof.id)
    ok, detail, _ = _paramiko_auth_ok(prof, password=pwd)
    return {
        "ok": ok,
        "live": True,
        "profile_id": profile_id,
        "remote_path": prof.remote_path,
        "detail": detail if not ok else "connected",
    }
