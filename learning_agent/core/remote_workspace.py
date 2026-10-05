"""Workspace remoto — SSH, sync e registro na Ravenna IDE (multi-servidor)."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from learning_agent.config import DATA_DIR
from learning_agent.core.ssh_config import parse_ssh_config, parse_ssh_target, ssh_config_path

PROFILES_PATH = DATA_DIR / "remote-servers.json"
LEGACY_PROFILE_PATH = DATA_DIR / "remote_app-remote.json"
CACHE_BASE = DATA_DIR / "remote-workspaces"
DEFAULT_REMOTE_PATH = ""


def _cache_has_content(cache: Path) -> bool:
    if not cache.is_dir():
        return False
    for child in cache.iterdir():
        if child.name in {".gitkeep", ".ravenna-remote.json"}:
            continue
        return True
    return False


def _effective_cache_path(prof: RemoteProfile) -> Path:
    """Cache canônico — respeita cache_dir e registry IDE (ex.: remote_app-teste no VM)."""
    if prof.cache_dir.strip():
        return Path(prof.cache_dir).resolve()
    try:
        from learning_agent.core.workspace_roots import list_roots

        for root in list_roots():
            if root.get("id") == prof.id:
                candidate = Path(root["path"])
                if candidate.is_dir():
                    return candidate.resolve()
    except Exception:
        pass
    return prof.cache_path()


def _maybe_skip_initial_pull(prof: RemoteProfile, *, live: bool) -> dict[str, Any] | None:
    """Remote-live: não baixa o projeto inteiro no connect (estilo Cursor SSH)."""
    if not live:
        return None
    cache = _effective_cache_path(prof)
    reason = "remote-live-no-initial-pull"
    if _cache_has_content(cache):
        reason = "cache-local-exists-remote-live"
    return {
        "ok": True,
        "skipped": True,
        "reason": reason,
        "cache_path": str(cache),
        "bytes": 0,
        "profile": prof.sanitized(),
    }


class RemoteWorkspaceError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class RemoteProfile:
    id: str = ""
    label: str = "Servidor remoto"
    host: str = ""
    port: int = 22
    user: str = ""
    identity_file: str = ""
    ssh_config_alias: str = ""
    remote_path: str = DEFAULT_REMOTE_PATH
    cache_dir: str = ""
    use_remote_terminal: bool = True

    def cache_path(self) -> Path:
        if self.cache_dir:
            return Path(self.cache_dir).resolve()
        slug = self.id or "default"
        return (CACHE_BASE / slug).resolve()

    def display_target(self) -> str:
        if self.ssh_config_alias:
            return self.ssh_config_alias
        user = self.user or "root"
        host = self.host or "?"
        port = f":{self.port}" if self.port and self.port != 22 else ""
        return f"{user}@{host}{port}"

    def sanitized(self) -> dict[str, Any]:
        data = asdict(self)
        data["display_target"] = self.display_target()
        data["cache_path"] = str(self.cache_path())
        data["has_identity"] = bool(self.identity_file.strip())
        data["configured"] = bool(self.ssh_config_alias.strip() or self.host.strip())
        data.pop("identity_file", None)
        return data


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip()).strip("-").lower()
    return slug or "server"


def _unique_id(base: str, existing: set[str]) -> str:
    slug = _slugify(base)
    if slug not in existing:
        return slug
    i = 2
    while f"{slug}-{i}" in existing:
        i += 1
    return f"{slug}-{i}"


def _load_store() -> dict[str, Any]:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PROFILES_PATH.exists():
        _migrate_legacy_profile()
    if not PROFILES_PATH.exists():
        return {"version": 1, "active_terminal_id": "", "profiles": [], "recents": []}
    try:
        data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RemoteWorkspaceError(f"Registro remoto inválido: {exc}", status_code=500) from exc
    if not isinstance(data.get("profiles"), list):
        raise RemoteWorkspaceError("Registro remoto inválido: profiles ausente", status_code=500)
    return data


def _save_store(data: dict[str, Any]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _profile_from_dict(raw: dict[str, Any]) -> RemoteProfile:
    prof = RemoteProfile()
    for key, value in raw.items():
        if hasattr(prof, key) and value is not None:
            if key == "port":
                prof.port = int(value)
            else:
                setattr(prof, key, value)
    if prof.identity_file:
        prof.identity_file = str(Path(prof.identity_file).expanduser())
    return prof


def _migrate_legacy_profile() -> None:
    if not LEGACY_PROFILE_PATH.exists():
        return
    try:
        raw = json.loads(LEGACY_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, dict):
        return
    prof = _profile_from_dict(raw)
    if not prof.id:
        prof.id = _slugify(prof.label or prof.ssh_config_alias or prof.host or "default")
    _save_store(
        {
            "version": 1,
            "active_terminal_id": prof.id,
            "profiles": [asdict(prof)],
            "recents": [],
        }
    )


def _env_overrides() -> dict[str, Any]:
    mapping = {
        "host": ("REMOTE_SSH_HOST", "remoteapp_SSH_HOST"),
        "user": ("REMOTE_SSH_USER", "remoteapp_SSH_USER"),
        "port": ("REMOTE_SSH_PORT", "remoteapp_SSH_PORT"),
        "identity_file": ("REMOTE_SSH_IDENTITY", "remoteapp_SSH_IDENTITY"),
        "ssh_config_alias": ("REMOTE_SSH_ALIAS", "remoteapp_SSH_ALIAS"),
        "remote_path": ("REMOTE_SSH_PATH", "remoteapp_REMOTE_PATH"),
        "label": ("REMOTE_WORKSPACE_LABEL", "remoteapp_WORKSPACE_LABEL"),
    }
    out: dict[str, Any] = {}
    for key, env_keys in mapping.items():
        raw = ""
        for env_key in env_keys:
            raw = os.environ.get(env_key, "").strip()
            if raw:
                break
        if not raw:
            continue
        if key == "port":
            try:
                out[key] = int(raw)
            except ValueError as exc:
                raise RemoteWorkspaceError(f"{env_keys[0]} inválido: {raw}") from exc
        else:
            out[key] = raw
    term = os.environ.get("REMOTE_SSH_TERMINAL", os.environ.get("remoteapp_SSH_TERMINAL", "")).strip().lower()
    if term in {"0", "false", "no", "off"}:
        out["use_remote_terminal"] = False
    elif term in {"1", "true", "yes", "on"}:
        out["use_remote_terminal"] = True
    return out


def list_profiles() -> list[RemoteProfile]:
    data = _load_store()
    profiles = [_profile_from_dict(p) for p in data["profiles"] if isinstance(p, dict)]
    env = _env_overrides()
    if env and not profiles:
        prof = RemoteProfile(id="env-default", label=env.get("label", "Servidor remoto"))
        for key, value in env.items():
            setattr(prof, key, value)
        profiles = [prof]
    return profiles


def get_profile(profile_id: str) -> RemoteProfile:
    if not profile_id:
        raise RemoteWorkspaceError("ID do servidor obrigatório", status_code=400)
    for prof in list_profiles():
        if prof.id == profile_id:
            return prof
    raise RemoteWorkspaceError(f"Servidor '{profile_id}' não encontrado", status_code=404)


def save_profile(profile: RemoteProfile) -> RemoteProfile:
    data = _load_store()
    profiles_raw = [p for p in data["profiles"] if isinstance(p, dict)]
    if not profile.id:
        existing_ids = {p.get("id", "") for p in profiles_raw}
        profile.id = _unique_id(profile.label or profile.ssh_config_alias or profile.host or "server", existing_ids)
    if profile.ssh_config_alias and not re.fullmatch(r"[\w.\-]+", profile.ssh_config_alias):
        raise RemoteWorkspaceError("Alias SSH inválido", status_code=400)
    if not profile.remote_path.strip():
        profile.remote_path = DEFAULT_REMOTE_PATH

    updated = False
    for i, raw in enumerate(profiles_raw):
        if raw.get("id") == profile.id:
            profiles_raw[i] = asdict(profile)
            updated = True
            break
    if not updated:
        profiles_raw.append(asdict(profile))

    data["profiles"] = profiles_raw
    if not data.get("active_terminal_id"):
        data["active_terminal_id"] = profile.id
    _save_store(data)
    return profile


def delete_profile(profile_id: str) -> None:
    data = _load_store()
    before = len(data["profiles"])
    data["profiles"] = [p for p in data["profiles"] if p.get("id") != profile_id]
    if len(data["profiles"]) == before:
        raise RemoteWorkspaceError(f"Servidor '{profile_id}' não encontrado", status_code=404)
    if data.get("active_terminal_id") == profile_id:
        data["active_terminal_id"] = data["profiles"][0]["id"] if data["profiles"] else ""
    _save_store(data)


def load_profile(profile_id: str | None = None) -> RemoteProfile:
    """Compat: carrega perfil por id ou o primeiro / env."""
    if profile_id:
        return get_profile(profile_id)
    profiles = list_profiles()
    if profiles:
        data = _load_store()
        active = data.get("active_terminal_id")
        for prof in profiles:
            if prof.id == active:
                return prof
        return profiles[0]
    prof = RemoteProfile(id="default")
    for key, value in _env_overrides().items():
        setattr(prof, key, value)
    return prof


def set_active_terminal(profile_id: str) -> RemoteProfile:
    prof = get_profile(profile_id)
    data = _load_store()
    data["active_terminal_id"] = profile_id
    _save_store(data)
    return prof


def update_profile_from_body(profile_id: str | None, body: dict[str, Any]) -> RemoteProfile:
    if profile_id:
        prof = get_profile(profile_id)
    else:
        prof = RemoteProfile()
        if body.get("id"):
            prof.id = str(body["id"])
    allowed = {
        "id",
        "label",
        "host",
        "port",
        "user",
        "identity_file",
        "ssh_config_alias",
        "remote_path",
        "cache_dir",
        "use_remote_terminal",
    }
    for key, value in body.items():
        if key not in allowed:
            continue
        if key == "port":
            prof.port = int(value)
        else:
            setattr(prof, key, value)
    return save_profile(prof)


def _record_recent(prof: RemoteProfile) -> None:
    data = _load_store()
    recents: list[dict[str, Any]] = [
        r for r in data.get("recents", []) if isinstance(r, dict) and r.get("target") != prof.display_target()
    ]
    recents.insert(
        0,
        {
            "target": prof.ssh_config_alias or prof.display_target(),
            "remote_path": prof.remote_path,
            "label": prof.label,
            "profile_id": prof.id,
            "hostname": prof.host,
            "connected_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    data["recents"] = recents[:16]
    _save_store(data)


def list_ssh_hosts() -> dict[str, Any]:
    """Hosts do ~/.ssh/config + recentes + perfis salvos (como Cursor)."""
    config_hosts = [h.to_dict() for h in parse_ssh_config()]
    config_names = {h["name"].lower() for h in config_hosts}

    data = _load_store()
    recents_raw = data.get("recents", [])
    recents: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in recents_raw if isinstance(recents_raw, list) else []:
        if not isinstance(entry, dict):
            continue
        target = str(entry.get("target", "")).strip()
        if not target or target.lower() in seen:
            continue
        seen.add(target.lower())
        label = entry.get("label") or target
        hostname = entry.get("hostname", "")
        display = f"{label} {hostname}".strip() if hostname and hostname not in label else label
        recents.append(
            {
                "target": target,
                "label": display,
                "remote_path": entry.get("remote_path", ""),
                "source": "recent",
                "profile_id": entry.get("profile_id", ""),
            }
        )

    saved: list[dict[str, Any]] = []
    for prof in list_profiles():
        target = prof.ssh_config_alias or prof.display_target()
        key = target.lower()
        if key in seen:
            continue
        seen.add(key)
        hostname = prof.host
        label = prof.label or target
        display = f"{label} {hostname}".strip() if hostname and hostname not in label else label
        saved.append(
            {
                "target": target,
                "label": display,
                "remote_path": prof.remote_path,
                "source": "saved",
                "profile_id": prof.id,
            }
        )

    for host in config_hosts:
        key = host["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        user = host.get("user") or "root"
        port = int(host.get("port") or 22)
        port_suffix = f":{port}" if port != 22 else ""
        host["label"] = f"{host['name']} ({user}@{host.get('hostname') or host['name']}{port_suffix})"

    combined = list(recents)
    for host in config_hosts:
        if host["name"].lower() not in {r["target"].lower() for r in recents}:
            combined.append({**host, "target": host["name"], "label": host.get("label", host["name"]), "source": "config"})
    for item in saved:
        if item["target"].lower() not in {h.get("target", "").lower() for h in combined}:
            combined.append(item)

    return {
        "config_path": str(ssh_config_path()),
        "config_hosts": config_hosts,
        "recents": recents,
        "saved": saved,
        "hosts": combined,
    }


def _resolve_identity(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    path = Path(raw.strip().strip('"')).expanduser()
    if path.is_file():
        return str(path)
    ssh_rel = Path.home() / ".ssh" / raw.strip().strip('"')
    if ssh_rel.is_file():
        return str(ssh_rel)
    return ""


def _sanitize_profile_identity(prof: RemoteProfile) -> None:
    if prof.identity_file:
        prof.identity_file = _resolve_identity(prof.identity_file)


def profile_from_target(target: str, *, remote_path: str = "", label: str = "") -> RemoteProfile:
    try:
        parsed = parse_ssh_target(target)
    except ValueError as exc:
        raise RemoteWorkspaceError(str(exc), status_code=400) from exc

    alias = parsed.get("ssh_config_alias", "")
    parsed_host = parsed.get("host", "")
    parsed_user = parsed.get("user", "")
    parsed_port = int(parsed.get("port", 22) or 22)

    existing: RemoteProfile | None = None
    for prof in list_profiles():
        if alias and prof.ssh_config_alias == alias:
            existing = prof
            break
        if (
            not alias
            and prof.host == parsed_host
            and (prof.user or "") == parsed_user
            and int(prof.port or 22) == parsed_port
        ):
            existing = prof
            break

    if existing:
        prof = existing
    else:
        prof = RemoteProfile(label=label or parsed.get("label") or target)

    if alias:
        prof.ssh_config_alias = alias
    else:
        prof.ssh_config_alias = ""
    prof.host = parsed_host or prof.host
    prof.user = parsed_user or prof.user
    prof.port = parsed_port
    if parsed.get("identity_file"):
        prof.identity_file = _resolve_identity(str(parsed["identity_file"]))
    _sanitize_profile_identity(prof)
    if remote_path.strip():
        prof.remote_path = remote_path.strip()
    elif not prof.remote_path:
        prof.remote_path = ""
    if label.strip():
        prof.label = label.strip()
    elif parsed.get("label"):
        prof.label = str(parsed["label"])
    return save_profile(prof)


def browse_remote_directory(
    *,
    target: str | None = None,
    profile_id: str | None = None,
    path: str = "~",
    password: str = "",
    username: str = "",
) -> dict[str, Any]:
    if target:
        prof = profile_from_target(target)
    elif profile_id:
        prof = get_profile(profile_id)
    else:
        raise RemoteWorkspaceError("Informe o host SSH", status_code=400)

    prof = _apply_username_override(prof, username)
    connect_as = _format_connect_identity(prof)

    if password:
        try:
            result = browse_remote_directory_paramiko(prof, path, password=password)
            result["connect_as"] = connect_as
            result["auth_method"] = "password-paramiko"
            return result
        except Exception as exc:
            err = str(exc)
            auth_fail = "Permission denied" in err or "Authentication failed" in err or "password" in err.lower()
            return {
                "ok": False,
                "error": err,
                "connect_as": connect_as,
                "auth_required": auth_fail,
                "needs_password": auth_fail,
                "profile": prof.sanitized(),
            }

    start = (path or "~").strip() or "~"
    cmd = (
        f"cd {shlex.quote(start)} 2>/dev/null || cd ~; "
        "pwd; ls -1Ap 2>/dev/null | head -400"
    )
    proc = _run_ssh(prof, cmd, timeout=45)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        err = stderr or "Não foi possível listar o servidor"
        auth_fail = "Permission denied" in err or "password" in err.lower()
        return {
            "ok": False,
            "error": err,
            "connect_as": connect_as,
            "auth_required": auth_fail,
            "needs_password": auth_fail,
            "profile": prof.sanitized(),
        }

    return _parse_browse_ls_output(stdout, prof, connect_as)


def connect_ssh_target(
    target: str,
    *,
    remote_path: str = "",
    label: str = "",
    skip_sync: bool = False,
    password: str = "",
    username: str = "",
    live: bool = True,
) -> dict[str, Any]:
    prof = profile_from_target(target, label=label)
    prof = _apply_username_override(prof, username)
    connect_as = _format_connect_identity(prof)
    if not remote_path.strip():
        if password:
            ok, hostname_or_err, pwd = _password_auth_probe(prof, password=password)
            return {
                "ok": True,
                "step": "browse",
                "default_path": pwd or "~",
                "hostname": hostname_or_err if ok else prof.host,
                "connect_as": connect_as,
                "auth_ok": ok,
                "auth_hint": "" if ok else hostname_or_err,
                "needs_password": not ok,
                "profile": prof.sanitized(),
            }
        test = test_connection(prof)
        pwd = ""
        if test.get("ok"):
            probe = _run_ssh(prof, "pwd", timeout=15)
            if probe.returncode == 0:
                pwd = (probe.stdout or "").strip()
        err = test.get("error") or ""
        auth_fail = not test.get("ok") and (
            "Permission denied" in err or "password" in err.lower()
        )
        return {
            "ok": True,
            "step": "browse",
            "default_path": pwd or "~",
            "hostname": test.get("hostname", prof.host),
            "connect_as": connect_as,
            "auth_ok": bool(test.get("ok")),
            "auth_hint": err if not test.get("ok") else "",
            "needs_password": auth_fail,
            "profile": prof.sanitized(),
        }

    prof = profile_from_target(target, remote_path=remote_path, label=label)
    prof = _apply_username_override(prof, username)
    connect_as = _format_connect_identity(prof)
    if password:
        ok, err, _ = _password_auth_probe(prof, password=password)
        if not ok:
            raise RemoteWorkspaceError(err or "Senha SSH inválida", status_code=401)
        resolved = _resolve_remote_path_on_server(prof, prof.remote_path or "~", password=password)
        prof.remote_path = resolved
        save_profile(prof)
        if live and password.strip():
            from learning_agent.core import remote_live

            remote_live.save_session_password(prof.id, password)
        skipped = _maybe_skip_initial_pull(prof, live=live)
        sync = skipped if skipped else sync_pull_with_password(prof, password)
        _record_recent(prof)
        root_entry = _register_remote_cache_root(prof, live=live)
        return {
            "ok": True,
            "step": "done",
            "sync": sync,
            "sync_skipped": bool(skipped),
            "root": root_entry,
            "cache_path": str(prof.cache_path()),
            "connect_as": connect_as,
            "live": live,
            "profile": prof.sanitized(),
        }

    test = test_connection(prof)
    if not test.get("ok"):
        err = test.get("error") or "SSH falhou"
        if "Permission denied" in err or "password" in err.lower():
            return attach_remote_without_sync(prof)
        raise RemoteWorkspaceError(err, status_code=502)

    _record_recent(prof)
    if skip_sync:
        return {"ok": True, "step": "done", "profile": prof.sanitized(), "test": test}

    result = ensure_workspace_root(prof, live=live)
    result["step"] = "done"
    result["live"] = live
    return result


def open_ssh_config() -> dict[str, Any]:
    path = ssh_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# SSH hosts — ex.:\n# Host meu-servidor\n#   HostName 203.0.113.10\n#   User ubuntu\n#   IdentityFile ~/.ssh/key.pem\n", encoding="utf-8")
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as exc:
        return {"ok": True, "path": str(path), "opened": False, "error": str(exc)}
    return {"ok": True, "path": str(path), "opened": True}


def _ssh_base_args(profile: RemoteProfile, *, batch: bool = True) -> list[str]:
    args = [
        "ssh",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ServerAliveInterval=30",
    ]
    if batch:
        args.extend(["-o", "BatchMode=yes"])
    if profile.ssh_config_alias:
        return args
    if profile.port and profile.port != 22:
        args.extend(["-p", str(profile.port)])
    _sanitize_profile_identity(profile)
    if profile.identity_file:
        args.extend(["-i", profile.identity_file])
    return args


def _ssh_target(profile: RemoteProfile) -> str:
    if profile.ssh_config_alias:
        return profile.ssh_config_alias
    if not profile.host:
        raise RemoteWorkspaceError("Host ou alias SSH obrigatório", status_code=400)
    user = profile.user or "root"
    return f"{user}@{profile.host}"


def _run_ssh(
    profile: RemoteProfile,
    remote_cmd: str,
    *,
    timeout: int = 120,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    args = _ssh_base_args(profile) + [_ssh_target(profile), remote_cmd]
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RemoteWorkspaceError("Timeout SSH", status_code=504) from exc
    except OSError as exc:
        raise RemoteWorkspaceError(f"SSH indisponível: {exc}", status_code=503) from exc


_ASKPASS_HELPER = CACHE_BASE / "_ssh_askpass_helper.py"


def _ensure_askpass_helper() -> Path:
    _ASKPASS_HELPER.parent.mkdir(parents=True, exist_ok=True)
    if not _ASKPASS_HELPER.exists():
        _ASKPASS_HELPER.write_text(
            'import os\nprint(os.environ.get("RAVENNA_SSH_ASKPASS_PASSWORD", ""), end="")\n',
            encoding="utf-8",
        )
    return _ASKPASS_HELPER


def _ssh_password_base_args(profile: RemoteProfile) -> list[str]:
    args = [
        "ssh",
        "-o",
        "BatchMode=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "PreferredAuthentications=password,keyboard-interactive",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ServerAliveInterval=30",
    ]
    if profile.ssh_config_alias:
        return args
    if profile.port and profile.port != 22:
        args.extend(["-p", str(profile.port)])
    return args


def _run_ssh_with_password(
    profile: RemoteProfile,
    remote_cmd: str,
    password: str,
    *,
    timeout: int = 120,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Executa comando remoto com senha via Paramiko (confiável no Docker; sem ssh-askpass)."""
    if not password.strip():
        raise RemoteWorkspaceError("Senha SSH obrigatória", status_code=400)
    try:
        client = _open_paramiko_client(profile, password=password, timeout=min(timeout, 45))
    except Exception as exc:
        raise RemoteWorkspaceError(f"SSH recusado: {exc}", status_code=401) from exc
    try:
        _, stdout, stderr = client.exec_command(remote_cmd, timeout=timeout)
        if text:
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
        else:
            out = stdout.read()
            err = stderr.read()
        code = stdout.channel.recv_exit_status()
        return subprocess.CompletedProcess([], code, out, err)
    except Exception as exc:
        raise RemoteWorkspaceError(f"Falha no comando SSH: {exc}", status_code=502) from exc
    finally:
        client.close()


def _resolve_remote_path_on_server(
    prof: RemoteProfile,
    path: str,
    *,
    password: str = "",
) -> str:
    start = (path or "~").strip() or "~"
    cmd = f"cd {shlex.quote(start)} && pwd"
    if password:
        proc = _run_ssh_with_password(prof, cmd, password, timeout=30)
    else:
        proc = _run_ssh(prof, cmd, timeout=30)
    if proc.returncode != 0:
        raise RemoteWorkspaceError(
            (proc.stderr or proc.stdout or "Caminho remoto inválido").strip(),
            status_code=400,
        )
    stdout = proc.stdout or b""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    resolved = stdout.strip()
    return resolved or start


def _parse_browse_ls_output(
    stdout: str,
    prof: RemoteProfile,
    connect_as: str,
    *,
    auth_method: str = "key",
) -> dict[str, Any]:
    lines = stdout.splitlines()
    current_path = lines[0].strip()
    entries: list[dict[str, str]] = []
    for raw in lines[1:]:
        if not raw.strip():
            continue
        is_dir = raw.endswith("/")
        name = raw.rstrip("/")
        if not name or name in {".", ".."}:
            continue
        full = f"{current_path.rstrip('/')}/{name}"
        entries.append({"name": name, "path": full, "kind": "dir" if is_dir else "file"})

    entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, e["name"].lower()))
    parent = current_path.rstrip("/")
    parent = parent.rsplit("/", 1)[0] if "/" in parent.strip("/") else "/"
    if current_path in {"/", ""}:
        parent = ""

    return {
        "ok": True,
        "path": current_path,
        "parent": parent,
        "entries": entries,
        "profile": prof.sanitized(),
        "connect_as": connect_as,
        "auth_method": auth_method,
    }


def _format_connect_identity(prof: RemoteProfile) -> str:
    hostname, port, username = _profile_connect_params(prof)
    port_suffix = f":{port}" if port != 22 else ""
    return f"{username}@{hostname}{port_suffix}"


def _apply_username_override(prof: RemoteProfile, username: str = "") -> RemoteProfile:
    name = username.strip()
    if not name:
        return prof
    prof.user = name
    prof.ssh_config_alias = ""
    return prof


def _profile_connect_params(prof: RemoteProfile) -> tuple[str, int, str]:
    if prof.ssh_config_alias:
        for host in parse_ssh_config():
            if host.name == prof.ssh_config_alias:
                return (
                    host.hostname or host.name,
                    int(host.port or 22),
                    host.user or prof.user or "root",
                )
        return prof.ssh_config_alias, int(prof.port or 22), prof.user or "root"
    if not prof.host:
        raise RemoteWorkspaceError("Host SSH obrigatório", status_code=400)
    return prof.host, int(prof.port or 22), prof.user or "root"


def _open_paramiko_client(prof: RemoteProfile, *, password: str = "", timeout: int = 20):
    import paramiko

    hostname, port, username = _profile_connect_params(prof)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if not password.strip():
        kwargs: dict[str, Any] = {
            "hostname": hostname,
            "port": port,
            "username": username,
            "timeout": timeout,
            "banner_timeout": timeout,
            "auth_timeout": timeout,
            "allow_agent": True,
            "look_for_keys": True,
        }
        key_file = prof.identity_file.strip()
        if key_file:
            expanded = Path(key_file).expanduser()
            if expanded.is_file():
                kwargs["key_filename"] = str(expanded)
        client.connect(**kwargs)
        return client

    connect_kwargs: dict[str, Any] = {
        "hostname": hostname,
        "port": port,
        "username": username,
        "password": password,
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
        "allow_agent": False,
        "look_for_keys": False,
    }
    try:
        client.connect(**connect_kwargs)
    except paramiko.AuthenticationException as exc:
        who = f"{username}@{hostname}:{port}"
        raise paramiko.AuthenticationException(f"{exc} (usuário SSH: {who})") from exc
    return client


def _resolve_remote_path_paramiko(client: Any, path: str) -> str:
    start = (path or "~").strip() or "~"
    if start == "~":
        _, stdout, _ = client.exec_command("cd ~ && pwd")
        return stdout.read().decode("utf-8", errors="replace").strip()
    if start.startswith("~/"):
        _, stdout, _ = client.exec_command(f"cd {shlex.quote(start)} && pwd")
        resolved = stdout.read().decode("utf-8", errors="replace").strip()
        return resolved or start
    return start


def browse_remote_directory_paramiko(
    prof: RemoteProfile,
    path: str,
    *,
    password: str = "",
) -> dict[str, Any]:
    client = _open_paramiko_client(prof, password=password)
    try:
        current_path = _resolve_remote_path_paramiko(client, path)
        sftp = client.open_sftp()
        try:
            entries: list[dict[str, str]] = []
            for attr in sftp.listdir_attr(current_path):
                name = attr.filename
                if not name or name in {".", ".."}:
                    continue
                is_dir = stat.S_ISDIR(attr.st_mode)
                full = f"{current_path.rstrip('/')}/{name}"
                entries.append({"name": name, "path": full, "kind": "dir" if is_dir else "file"})
        finally:
            sftp.close()
        entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, e["name"].lower()))
        parent = current_path.rstrip("/")
        parent = parent.rsplit("/", 1)[0] if "/" in parent.strip("/") else "/"
        if current_path in {"/", ""}:
            parent = ""
        return {
            "ok": True,
            "path": current_path,
            "parent": parent,
            "entries": entries,
            "profile": prof.sanitized(),
            "auth_method": "password" if password.strip() else "key",
        }
    finally:
        client.close()


def _password_auth_probe(prof: RemoteProfile, *, password: str = "") -> tuple[bool, str, str]:
    who = _format_connect_identity(prof)
    proc = _run_ssh_with_password(prof, "echo RAVENNA_OK && hostname && pwd", password, timeout=30)
    stdout = (proc.stdout or "").strip()
    if proc.returncode == 0 and "RAVENNA_OK" in stdout:
        lines = stdout.splitlines()
        hostname = lines[1] if len(lines) > 1 else prof.host
        pwd = lines[2] if len(lines) > 2 else ""
        return True, hostname, pwd
    err = (proc.stderr or proc.stdout or "Authentication failed").strip()
    try:
        ok, hostname, pwd = _paramiko_auth_ok(prof, password=password)
        if ok:
            return ok, hostname, pwd
        err = hostname
    except Exception as exc:
        err = str(exc)
    if "Authentication failed" in err and who not in err:
        err = f"{err} (usuário SSH: {who})"
    return False, err, ""


def _paramiko_auth_ok(prof: RemoteProfile, *, password: str = "") -> tuple[bool, str, str]:
    try:
        client = _open_paramiko_client(prof, password=password, timeout=20)
        try:
            _, stdout, stderr = client.exec_command("echo RAVENNA_OK && hostname && pwd")
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            if "RAVENNA_OK" not in out:
                return False, err or out or "auth falhou", ""
            lines = out.splitlines()
            hostname = lines[1] if len(lines) > 1 else prof.host
            pwd = lines[2] if len(lines) > 2 else ""
            return True, hostname, pwd
        finally:
            client.close()
    except Exception as exc:
        return False, str(exc), ""


def _scp_base_args(profile: RemoteProfile) -> list[str]:
    args = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if profile.ssh_config_alias:
        return args
    if profile.port and profile.port != 22:
        args.extend(["-P", str(profile.port)])
    if profile.identity_file:
        args.extend(["-i", profile.identity_file])
    return args


def _scp_target(profile: RemoteProfile, remote_file: str) -> str:
    if profile.ssh_config_alias:
        return f"{profile.ssh_config_alias}:{remote_file}"
    return f"{_ssh_target(profile)}:{remote_file}"


def _is_windows_remote_path(path: str) -> bool:
    p = (path or "").strip()
    return len(p) >= 2 and p[1] == ":" and p[0].isalpha()


def test_connection(profile: RemoteProfile | None = None, *, profile_id: str | None = None) -> dict[str, Any]:
    prof = profile or load_profile(profile_id)
    if not prof.ssh_config_alias and not prof.host:
        return {
            "ok": False,
            "error": "Preencha alias SSH ou host em Workspaces → Adicionar → Servidor remoto.",
            "profile": prof.sanitized(),
        }

    win = _is_windows_remote_path(prof.remote_path)
    probe_cmd = "echo RAVENNA_OK && hostname" if win else "echo RAVENNA_OK && hostname && pwd"
    probe = _run_ssh(prof, probe_cmd, timeout=30)
    stdout = (probe.stdout or "").strip()
    stderr = (probe.stderr or "").strip()
    if probe.returncode != 0 or "RAVENNA_OK" not in stdout:
        err = stderr or stdout or f"exit {probe.returncode}"
        return {"ok": False, "error": err, "profile": prof.sanitized()}

    remote_path = prof.remote_path.rstrip("/")
    path_ok = True
    listing = ""
    if remote_path:
        if win:
            path_cmd = (
                f'powershell -NoProfile -Command "if (Test-Path '
                f"'{remote_path.replace(chr(39), chr(39)+chr(39))}'"
                f') {{ echo PATH_OK }} else {{ echo PATH_MISSING }}"'
            )
        else:
            path_cmd = f"test -d {shlex.quote(remote_path)} && echo PATH_OK || echo PATH_MISSING"
        path_probe = _run_ssh(prof, path_cmd, timeout=30)
        path_ok = "PATH_OK" in (path_probe.stdout or "")
        if path_ok:
            ls = _run_ssh(prof, f"ls -la {shlex.quote(remote_path)} | head -20", timeout=30)
            listing = (ls.stdout or "").strip()

    lines = [ln for ln in stdout.splitlines() if ln != "RAVENNA_OK"]
    return {
        "ok": True,
        "hostname": lines[0] if lines else "",
        "remote_path": remote_path,
        "remote_path_exists": path_ok,
        "listing_preview": listing,
        "profile": prof.sanitized(),
    }


def sync_pull(profile: RemoteProfile | None = None, *, profile_id: str | None = None) -> dict[str, Any]:
    prof = profile or load_profile(profile_id)
    test = test_connection(prof)
    if not test.get("ok"):
        err = test.get("error") or "SSH falhou"
        if "Permission denied" in err or "password" in err.lower():
            raise RemoteWorkspaceError(
                f"{err} — informe a senha SSH no Connect ou configure chave.",
                status_code=502,
            ) from None
        raise RemoteWorkspaceError(err, status_code=502)
    if not prof.remote_path.strip():
        raise RemoteWorkspaceError("Caminho remoto obrigatório", status_code=400)
    resolved = _resolve_remote_path_on_server(prof, prof.remote_path)
    prof.remote_path = resolved
    save_profile(prof)
    return _sync_pull_resolved(prof, resolved)


def sync_pull_with_password(prof: RemoteProfile, password: str) -> dict[str, Any]:
    if not password:
        raise RemoteWorkspaceError("Senha SSH obrigatória para sync", status_code=400)
    if not prof.remote_path.strip():
        raise RemoteWorkspaceError("Caminho remoto obrigatório", status_code=400)
    resolved = _resolve_remote_path_on_server(prof, prof.remote_path, password=password)
    prof.remote_path = resolved
    save_profile(prof)
    return _sync_pull_resolved(prof, resolved, password=password)


def _sync_pull_resolved(
    prof: RemoteProfile,
    remote: str,
    *,
    password: str = "",
) -> dict[str, Any]:
    cache = prof.cache_path()
    cache.mkdir(parents=True, exist_ok=True)
    remote_q = shlex.quote(remote)
    tar_cmd = f"tar -cf - -C {remote_q} ."
    if password:
        archive = _run_ssh_with_password(prof, tar_cmd, password, timeout=600, text=False)
    else:
        archive = _run_ssh(prof, tar_cmd, timeout=600, text=False)
    if archive.returncode != 0:
        stderr = archive.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise RemoteWorkspaceError((stderr or "falha no tar remoto").strip(), status_code=502)

    payload = archive.stdout or b""
    if not payload:
        raise RemoteWorkspaceError("Sync vazio — verifique o caminho remoto", status_code=502)

    for child in cache.iterdir():
        if child.name in {".gitkeep", ".ravenna-remote.json"}:
            continue
        if child.is_dir():
            import shutil

            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)

    with tarfile.open(fileobj=BytesIO(payload), mode="r:") as tar:
        tar.extractall(cache, filter="data")

    return {
        "ok": True,
        "cache_path": str(cache),
        "remote_path": remote,
        "bytes": len(payload),
        "profile": prof.sanitized(),
    }


def _resolve_deploy_cache(prof: RemoteProfile) -> Path:
    """Cache usado no push — alinha com workspace IDE (ex.: luis-132-255-110-213)."""
    from learning_agent.core.workspace_roots import find_root, get_root_path

    if prof.id and find_root(prof.id):
        try:
            return get_root_path(prof.id).resolve()
        except Exception:
            pass
    return _effective_cache_path(prof)


def sync_push(
    profile: RemoteProfile | None = None,
    *,
    profile_id: str | None = None,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    prof = profile or load_profile(profile_id)
    test = test_connection(prof)
    if not test.get("ok"):
        err = test.get("error") or "SSH falhou"
        if "Permission denied" in err or "password" in err.lower():
            raise RemoteWorkspaceError(
                f"{err} — sync exige chave SSH. Terminal da IDE aceita senha (Ctrl+`).",
                status_code=502,
            ) from None
        raise RemoteWorkspaceError(err, status_code=502)
    if not prof.remote_path.strip():
        raise RemoteWorkspaceError("Caminho remoto obrigatório", status_code=400)

    cache = _resolve_deploy_cache(prof)
    if not cache.is_dir():
        raise RemoteWorkspaceError("Cache local inexistente — anexe o servidor primeiro", status_code=404)

    remote = prof.remote_path.rstrip("/")
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:") as tar:
        if paths:
            for rel in paths:
                rel_path = rel.replace("\\", "/").lstrip("/")
                local = (cache / rel_path).resolve()
                if not str(local).startswith(str(cache.resolve())):
                    raise RemoteWorkspaceError(f"Path fora do cache: {rel}", status_code=403)
                if local.is_file():
                    tar.add(local, arcname=rel_path)
        else:
            for item in cache.rglob("*"):
                if item.is_file() and item.name != ".gitkeep":
                    tar.add(item, arcname=item.relative_to(cache).as_posix())

    payload = buffer.getvalue()
    if not payload:
        return {"ok": True, "pushed": False, "reason": "nada para enviar", "profile": prof.sanitized()}

    tmp_name = f"ravenna-remote-sync-{prof.id}.tar"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tmp:
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        remote_q = shlex.quote(remote)
        remote_tmp = f"/tmp/{tmp_name}"
        scp_args = _scp_base_args(prof) + [tmp_path, _scp_target(prof, remote_tmp)]
        scp = subprocess.run(scp_args, capture_output=True, text=True, timeout=180, check=False)
        if scp.returncode != 0:
            err = (scp.stderr or scp.stdout or "scp falhou").strip()
            raise RemoteWorkspaceError(err, status_code=502)
        extract = _run_ssh(
            prof,
            f"tar -xf {shlex.quote(remote_tmp)} -C {remote_q} && rm -f {shlex.quote(remote_tmp)}",
            timeout=300,
        )
        if extract.returncode != 0:
            err = (extract.stderr or extract.stdout or "extração remota falhou").strip()
            raise RemoteWorkspaceError(err, status_code=502)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "ok": True,
        "pushed": True,
        "bytes": len(payload),
        "paths": paths or ["*"],
        "profile": prof.sanitized(),
    }


def sync_push_with_password(
    prof: RemoteProfile,
    password: str,
    *,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    if not password.strip():
        raise RemoteWorkspaceError("Senha SSH obrigatória para push", status_code=400)
    if not prof.remote_path.strip():
        raise RemoteWorkspaceError("Caminho remoto obrigatório", status_code=400)

    cache = _resolve_deploy_cache(prof)
    if not cache.is_dir():
        raise RemoteWorkspaceError("Cache local inexistente — anexe o servidor primeiro", status_code=404)

    remote = prof.remote_path.rstrip("/")
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:") as tar:
        if paths:
            for rel in paths:
                rel_path = rel.replace("\\", "/").lstrip("/")
                local = (cache / rel_path).resolve()
                if not str(local).startswith(str(cache.resolve())):
                    raise RemoteWorkspaceError(f"Path fora do cache: {rel}", status_code=403)
                if local.is_file():
                    tar.add(local, arcname=rel_path)
        else:
            for item in cache.rglob("*"):
                if item.is_file() and item.name != ".gitkeep":
                    tar.add(item, arcname=item.relative_to(cache).as_posix())

    payload = buffer.getvalue()
    if not payload:
        return {"ok": True, "pushed": False, "reason": "nada para enviar", "profile": prof.sanitized()}

    tmp_name = f"ravenna-remote-sync-{prof.id}.tar"
    remote_tmp = f"/tmp/{tmp_name}"
    client = _open_paramiko_client(prof, password=password, timeout=30)
    try:
        sftp = client.open_sftp()
        try:
            with sftp.file(remote_tmp, "wb") as remote_file:
                remote_file.write(payload)
        finally:
            sftp.close()
        extract_cmd = f"tar -xf {shlex.quote(remote_tmp)} -C {shlex.quote(remote)} && rm -f {shlex.quote(remote_tmp)}"
        _, stdout, stderr = client.exec_command(extract_cmd, timeout=300)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = (stderr.read() or stdout.read() or b"").decode("utf-8", errors="replace").strip()
            raise RemoteWorkspaceError(err or "extração remota falhou", status_code=502)
    finally:
        client.close()

    return {
        "ok": True,
        "pushed": True,
        "bytes": len(payload),
        "paths": paths or ["*"],
        "profile": prof.sanitized(),
        "auth_method": "password-paramiko",
    }


def sync_push_resilient(
    profile: RemoteProfile | None = None,
    *,
    profile_id: str | None = None,
    paths: list[str] | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Push via chave/agent; fallback para senha (env remoteapp_SSH_PASSWORD ou argumento)."""
    prof = profile or load_profile(profile_id)
    pwd = (password or os.environ.get("remoteapp_SSH_PASSWORD") or "").strip()
    test = test_connection(prof)
    if test.get("ok"):
        return sync_push(prof, paths=paths)
    err = test.get("error") or ""
    if pwd and ("Permission denied" in err or "password" in err.lower()):
        ok, _, _ = _paramiko_auth_ok(prof, password=pwd)
        if not ok:
            raise RemoteWorkspaceError("Senha SSH rejeitada pelo servidor", status_code=502)
        return sync_push_with_password(prof, pwd, paths=paths)
    if "Permission denied" in err or "password" in err.lower():
        raise RemoteWorkspaceError(
            f"{err} — defina remoteapp_SSH_PASSWORD ou configure chave SSH.",
            status_code=502,
        )
    raise RemoteWorkspaceError(err or "SSH falhou", status_code=502)


def _mark_root_remote_kind(root_id: str, *, kind: str = "remote-cache") -> None:
    from learning_agent.core.workspace_roots import REGISTRY_PATH

    if not REGISTRY_PATH.exists():
        return
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for root in data.get("roots", []):
        if root.get("id") == root_id:
            root["kind"] = kind
            break
    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _register_remote_cache_root(prof: RemoteProfile, *, live: bool = False) -> dict[str, Any] | None:
    from learning_agent.core import remote_live
    from learning_agent.core.workspace_roots import WorkspaceRootsError, add_folder_root, list_roots

    cache = _resolve_deploy_cache(prof)
    cache.mkdir(parents=True, exist_ok=True)
    set_active_terminal(prof.id)
    kind = "remote-live" if live else "remote-cache"

    # Reutiliza root existente para o cache (ex.: luis-132-255-110-213 → remote_app-teste)
    root_entry: dict[str, Any] | None = None
    cache_resolved = cache.resolve()
    for root in list_roots():
        try:
            if Path(root["path"]).resolve() == cache_resolved:
                root_entry = dict(root)
                break
        except OSError:
            continue

    if root_entry is None:
        try:
            root_entry = add_folder_root(str(cache), name=prof.label)
        except WorkspaceRootsError as exc:
            if exc.status_code != 409:
                raise
            root_entry = next(
                (dict(r) for r in list_roots() if Path(r["path"]).resolve() == cache_resolved),
                None,
            )

    if root_entry is None:
        root_entry = {"id": prof.id, "name": prof.label, "path": str(cache)}

    _mark_root_remote_kind(root_entry["id"], kind=kind)
    root_entry["kind"] = kind
    root_entry["remote_profile_id"] = prof.id

    meta_path = cache / ".ravenna-remote.json"
    meta_path.write_text(
        json.dumps(
            {
                "kind": kind,
                "profile_id": prof.id,
                "profile": prof.sanitized(),
                "remote_path": prof.remote_path,
                "display_target": prof.display_target(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if live:
        if password := remote_live.load_session_password(prof.id):
            remote_live.save_session_password(prof.id, password)
        remote_live.enable_live_for_profile(prof)
    _record_recent(prof)
    return root_entry


def attach_remote_without_sync(prof: RemoteProfile, *, warning: str = "") -> dict[str, Any]:
    root_entry = _register_remote_cache_root(prof)
    return {
        "ok": True,
        "step": "done",
        "sync_skipped": True,
        "warning": warning
        or "Servidor anexado sem sync — use o Terminal (Ctrl+`) para entrar com senha.",
        "root": root_entry,
        "cache_path": str(prof.cache_path()),
        "profile": prof.sanitized(),
    }


def ensure_workspace_root(
    profile: RemoteProfile | None = None,
    *,
    profile_id: str | None = None,
    live: bool = False,
) -> dict[str, Any]:
    prof = profile or load_profile(profile_id)
    cache = prof.cache_path()
    skipped = _maybe_skip_initial_pull(prof, live=live)
    if skipped:
        root_entry = _register_remote_cache_root(prof, live=live)
        return {
            "ok": True,
            "sync": skipped,
            "root": root_entry,
            "cache_path": str(cache),
            "profile": prof.sanitized(),
            "live": live,
        }
    sync = sync_pull(prof)
    root_entry = _register_remote_cache_root(prof, live=live)

    return {
        "ok": True,
        "sync": sync,
        "root": root_entry,
        "cache_path": str(cache),
        "profile": prof.sanitized(),
        "live": live,
    }


def remote_terminal_argv(profile_id: str | None = None) -> list[str] | None:
    prof = load_profile(profile_id)
    if not prof.use_remote_terminal:
        return None
    if not prof.ssh_config_alias and not prof.host:
        return None
    cd = f"cd {shlex.quote(prof.remote_path)} 2>/dev/null || cd ~" if prof.remote_path.strip() else "cd ~"
    args = _ssh_base_args(prof, batch=False) + [
        "-t",
        _ssh_target(prof),
        f"{cd}; exec bash -l",
    ]
    return args


# Compat legado (remote_app-remote.json path)
PROFILE_PATH = LEGACY_PROFILE_PATH
CACHE_DIR = CACHE_BASE / "default"