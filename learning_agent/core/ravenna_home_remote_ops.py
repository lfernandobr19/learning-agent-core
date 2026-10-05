"""Build/deploy Ravenna Home na VM host via SSH — autonomia roda dentro do container backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import paramiko

RAVENNA_HOME_COMPOSE_DIR = "/home/<USER>/learning-agent/ravenna-ide"
RAVENNA_HOME_FRONTEND = "/home/<USER>/learning-agent/ravenna-home/frontend"
COMPOSE_FILE_FLAGS = (
    "-f docker-compose.yml "
    "-f docker-compose.host-gpu.yml "
    "-f docker-compose.ravenna-home.yml "
)
BUILD_CMD = (
    f"cd {RAVENNA_HOME_COMPOSE_DIR} && docker compose {COMPOSE_FILE_FLAGS}"
    "build --no-cache ravenna-home-web"
)
BUILD_FAST_CMD = (
    f"cd {RAVENNA_HOME_COMPOSE_DIR} && docker compose {COMPOSE_FILE_FLAGS}"
    "build ravenna-home-web"
)
UP_CMD = (
    f"cd {RAVENNA_HOME_COMPOSE_DIR} && docker compose {COMPOSE_FILE_FLAGS}"
    "up -d ravenna-home-web"
)
ORPHAN_PATHS = (
    f"{RAVENNA_HOME_FRONTEND}/src/App.js",
    f"{RAVENNA_HOME_FRONTEND}/src/App.jsx",
    f"{RAVENNA_HOME_FRONTEND}/src/AppShell.jsx",
)


class RavennaHomeRemoteOpsError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def resolve_vm_password() -> str:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "").strip()
    if pwd:
        return pwd
    raise RavennaHomeRemoteOpsError("RAVENNA_VM_PASSWORD ausente — deploy remoto indisponível")


def resolve_vm_host() -> str:
    """Prefer an address reachable from the backend container."""
    configured = os.environ.get("RAVENNA_VM_HOST", "").strip()
    if configured and configured not in {"ravenna", "ravenna-vm"}:
        return configured
    return "host.docker.internal"


def resolve_vm_user() -> str:
    return os.environ.get("RAVENNA_VM_USER", "lfernando").strip() or "lfernando"


def is_ravenna_home_project(project_root: str | None) -> bool:
    root = (project_root or "").replace("\\", "/").strip("/").lower()
    if root == "ravenna-home" or root.startswith("ravenna-home/"):
        return True
    return root.endswith("/ravenna-home") or "/ravenna-home/" in f"/{root}/"


def is_ravenna_home_remote_command(command: str) -> bool:
    cmd = (command or "").strip().lower()
    if not cmd:
        return False
    if ("ravenna-home-web" in cmd or "ravenna-home-api" in cmd) and "compose" in cmd:
        return True
    if "npm run build" in cmd or "npm test" in cmd:
        if "frontend" in cmd or "ravenna-home" in cmd:
            return True
    if cmd.startswith("cd /home/<USER>/learning-agent/ravenna-ide"):
        return True
    return False


def run_ssh_command(command: str, *, timeout: int = 600) -> dict[str, Any]:
    hosts: list[str] = []
    primary = resolve_vm_host()
    hosts.append(primary)
    for alt in ("host.docker.internal", "172.17.0.1", "192.168.18.129", "ravenna"):
        if alt not in hosts:
            hosts.append(alt)
    user = resolve_vm_user()
    last: dict[str, Any] = {
        "command": command,
        "cwd": f"ssh://{user}@{primary}",
        "exit_code": 1,
        "output": "SSH não tentado",
        "remote": True,
        "remote_ok": False,
    }
    pwd = ""
    try:
        pwd = resolve_vm_password()
    except RavennaHomeRemoteOpsError as exc:
        pwd = ""
        last["output"] = exc.message

    key_paths = [
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_rsa",
        Path("/home/<USER>/.ssh/id_ed25519"),
        Path("/home/<USER>/.ssh/id_rsa"),
    ]
    pkey = None
    for key_path in key_paths:
        if not key_path.is_file():
            continue
        try:
            if "ed25519" in key_path.name:
                pkey = paramiko.Ed25519Key.from_private_key_file(str(key_path))
            else:
                pkey = paramiko.RSAKey.from_private_key_file(str(key_path))
            break
        except Exception:
            pkey = None

    for host in hosts:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            connect_kwargs: dict[str, Any] = {
                "hostname": host,
                "username": user,
                "timeout": 15,
                "allow_agent": True,
                "look_for_keys": True,
            }
            if pkey is not None:
                connect_kwargs["pkey"] = pkey
            if pwd:
                connect_kwargs["password"] = pwd
            client.connect(**connect_kwargs)
            remote_cmd = command
            if "docker compose" in command and "sudo" not in command:
                remote_cmd = (
                    "if docker info >/dev/null 2>&1; then "
                    f"{command}; "
                    f"else sudo -n {command}; fi"
                )
            _, stdout, stderr = client.exec_command(remote_cmd, timeout=timeout, get_pty=True)
            output = (stdout.read() or b"").decode("utf-8", "replace")
            err = (stderr.read() or b"").decode("utf-8", "replace")
            code = stdout.channel.recv_exit_status()
            if err.strip() and err.strip() not in output:
                output = f"{output}\n{err}".strip()
            return {
                "command": command,
                "cwd": f"ssh://{user}@{host}",
                "exit_code": code,
                "output": output[-6000:],
                "remote": True,
                "remote_ok": code == 0,
            }
        except Exception as exc:
            last = {
                "command": command,
                "cwd": f"ssh://{user}@{host}",
                "exit_code": 1,
                "output": str(exc),
                "remote": True,
                "remote_ok": False,
            }
        finally:
            client.close()
    return last


def preclean_frontend_orphans_ssh() -> dict[str, Any]:
    pwd = resolve_vm_password()
    paths = " ".join(ORPHAN_PATHS)
    cmd = f'echo "{pwd}" | sudo -S rm -fv {paths} 2>&1'
    return run_ssh_command(cmd, timeout=60)


def run_home_web_deploy(*, preclean: bool = True, fast_build: bool = False) -> dict[str, Any]:
    """Build + up ravenna-home-web on VM host."""
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    if preclean:
        clean = preclean_frontend_orphans_ssh()
        results.append(clean)
    build_cmd = BUILD_FAST_CMD if fast_build else BUILD_CMD
    build = run_ssh_command(build_cmd, timeout=600 if fast_build else 900)
    results.append(build)
    if build.get("exit_code") != 0:
        failures.append("docker compose build ravenna-home-web falhou no host VM")
    else:
        up = run_ssh_command(UP_CMD, timeout=180)
        results.append(up)
        if up.get("exit_code") != 0:
            failures.append("docker compose up ravenna-home-web falhou no host VM")
    return {
        "ok": not failures,
        "validated": True,
        "projectRoot": RAVENNA_HOME_FRONTEND,
        "commands": results,
        "failures": failures,
        "skippedReason": None,
        "remoteDeploy": True,
    }


def deploy_raven_link() -> dict[str, Any]:
    """Ensure ~/Raven_Link on Debian host: deps, core build, artifacts dir."""
    script = r"""
set -e
mkdir -p "$HOME/ravenna-artifacts" "$HOME/Raven_Link"
cd "$HOME/Raven_Link"
if [ ! -f package.json ]; then
  echo "MISSING_REPO: sync Raven_Link into ~/Raven_Link first"
  exit 42
fi
if command -v node >/dev/null 2>&1; then
  node -v
else
  echo "NODE_MISSING"
  exit 43
fi
npm ci || npm install
npm run build:core
mkdir -p "$HOME/ravenna-artifacts/raven-link"
cp -a package.json "$HOME/ravenna-artifacts/raven-link/" 2>/dev/null || true
echo OK
"""
    result = run_ssh_command(script, timeout=600)
    ok = int(result.get("exit_code") or 1) == 0
    return {
        "ok": ok,
        "target": "ravenna",
        "path": "~/Raven_Link",
        "artifacts": "~/ravenna-artifacts/raven-link",
        "ssh": result,
    }


def run_validation_deploy(
    changed_paths: list[str],
    project_root: str | None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not changed_paths:
        return {
            "ok": False,
            "validated": False,
            "projectRoot": project_root,
            "commands": [],
            "failures": ["Nenhum arquivo alterado — integração incompleta"],
            "skippedReason": None,
        }
    try:
        return run_home_web_deploy(preclean=bool((spec or {}).get("ravennaHomePreclean", True)))
    except RavennaHomeRemoteOpsError as exc:
        return {
            "ok": False,
            "validated": False,
            "projectRoot": project_root,
            "commands": [],
            "failures": [exc.message],
            "skippedReason": exc.message,
        }


def try_run_ravenna_home_remote_shell(
    command: str,
    *,
    project_root: str | None = None,
) -> dict[str, Any] | None:
    if not is_ravenna_home_project(project_root) and not is_ravenna_home_remote_command(command):
        return None
    cmd = (command or "").strip()
    if not cmd:
        return None
    if not is_ravenna_home_remote_command(cmd):
        return None
    normalized = cmd.lower()
    if "npm run build" in normalized or "npm test" in normalized:
        mapped = BUILD_CMD if "build" in normalized else cmd
        result = run_ssh_command(mapped, timeout=900)
    elif "ravenna-home-api" in normalized and (" up " in normalized or "build" in normalized):
        # Pass through compose commands that include home-api (machine-status rebuilds).
        result = run_ssh_command(cmd, timeout=900)
    elif " up " in normalized or normalized.endswith(" up -d ravenna-home-web"):
        result = run_ssh_command(UP_CMD, timeout=180)
    elif "build" in normalized and "ravenna-home-web" in normalized:
        result = run_ssh_command(BUILD_CMD, timeout=900)
    else:
        result = run_ssh_command(cmd, timeout=600)
    return {
        "command": cmd,
        "cwd": result.get("cwd", "remote-ssh"),
        "exit_code": result.get("exit_code"),
        "output": result.get("output", ""),
        "skipped": False,
        "remote": True,
        "remote_ok": bool(result.get("remote_ok")),
    }


def check_frontend_integration(root: Path) -> list[str]:
    from learning_agent.core import ravenna_home_delivery

    return ravenna_home_delivery.validate_filesystem(root, spec={"ravennaHomeDeploy": True})
