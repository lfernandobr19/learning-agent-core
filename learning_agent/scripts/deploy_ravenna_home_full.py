#!/usr/bin/env python3
"""Deploy Ravenna Home stack + motor updates to bare-metal ravenna."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
USER = "lfernando"
HOST = os.environ.get("RAVENNA_HOST", "100.91.89.48")
REMOTE_BASE = "/home/lfernando/learning-agent"

UPLOAD_DIRS = [
    (ROOT / "ravenna-home/backend", f"{REMOTE_BASE}/ravenna-home/backend"),
    (ROOT / "ravenna-home/frontend/src", f"{REMOTE_BASE}/ravenna-home/frontend/src"),
    (ROOT / "ravenna-home/frontend/public", f"{REMOTE_BASE}/ravenna-home/frontend/public"),
    (ROOT / "ravenna-windows-agent", f"{REMOTE_BASE}/ravenna-windows-agent"),
]

UPLOAD_FILES = [
    (ROOT / "ravenna-home/Dockerfile.backend", f"{REMOTE_BASE}/ravenna-home/Dockerfile.backend"),
    (ROOT / "ravenna-home/Dockerfile.frontend", f"{REMOTE_BASE}/ravenna-home/Dockerfile.frontend"),
    (ROOT / "ravenna-home/.env.example", f"{REMOTE_BASE}/ravenna-home/.env.example"),
    (ROOT / "ravenna-home/frontend/index.html", f"{REMOTE_BASE}/ravenna-home/frontend/index.html"),
    (ROOT / "ravenna-home/frontend/package.json", f"{REMOTE_BASE}/ravenna-home/frontend/package.json"),
    (ROOT / "ravenna-home/frontend/vite.config.ts", f"{REMOTE_BASE}/ravenna-home/frontend/vite.config.ts"),
    (ROOT / "learning_agent/core/chat.py", f"{REMOTE_BASE}/learning_agent/core/chat.py"),
    (ROOT / "learning_agent/core/agent_tools.py", f"{REMOTE_BASE}/learning_agent/core/agent_tools.py"),
    (ROOT / "learning_agent/core/windows_agent_client.py", f"{REMOTE_BASE}/learning_agent/core/windows_agent_client.py"),
    (ROOT / "learning_agent/core/android_agent_client.py", f"{REMOTE_BASE}/learning_agent/core/android_agent_client.py"),
    (ROOT / "learning_agent/identity.py", f"{REMOTE_BASE}/learning_agent/identity.py"),
    (ROOT / "ravenna-ide/docker-compose.ravenna-home.yml", f"{REMOTE_BASE}/ravenna-ide/docker-compose.ravenna-home.yml"),
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", "theme"}
SKIP_SUFFIXES = {".pyc", ".map"}


def _pwd() -> str:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if pwd:
        return pwd
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("RAVENNA_VM_PASSWORD="):
                return line.split("=", 1)[1]
    return ""


def _ensure_remote_dir(sftp: paramiko.SFTPClient, remote: str) -> None:
    parts = remote.strip("/").split("/")
    cur = ""
    for part in parts:
        cur = f"{cur}/{part}" if cur else part
        try:
            sftp.stat(cur)
        except OSError:
            sftp.mkdir(cur)


def upload_tree(sftp: paramiko.SFTPClient, local: Path, remote: str) -> int:
    count = 0
    for path in sorted(local.rglob("*")):
        rel = path.relative_to(local)
        if set(rel.parts) & SKIP_DIRS:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        rpath = f"{remote}/{rel.as_posix()}"
        if path.is_dir():
            try:
                sftp.stat(rpath)
            except OSError:
                try:
                    sftp.mkdir(rpath)
                except OSError:
                    pass
            continue
        _ensure_remote_dir(sftp, "/".join(rpath.split("/")[:-1]))
        try:
            sftp.put(str(path), rpath)
            count += 1
        except OSError as exc:
            print(f"WARN skip {rel}: {exc}", file=sys.stderr)
    return count


def main() -> int:
    pwd = _pwd()
    if not pwd:
        print("RAVENNA_VM_PASSWORD missing", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=pwd, timeout=30, allow_agent=True, look_for_keys=True)
    prep = (
        f"mkdir -p {REMOTE_BASE}/ravenna-windows-agent && "
        f"echo '{pwd}' | sudo -S chown -R {USER}:{USER} "
        f"{REMOTE_BASE}/ravenna-home {REMOTE_BASE}/learning_agent/core "
        f"{REMOTE_BASE}/ravenna-windows-agent 2>/dev/null || true"
    )
    client.exec_command(prep, timeout=60)[1].channel.recv_exit_status()
    sftp = client.open_sftp()
    total = 0
    try:
        for local, remote in UPLOAD_DIRS:
            if not local.is_dir():
                print(f"SKIP missing dir {local}", file=sys.stderr)
                continue
            n = upload_tree(sftp, local, remote)
            total += n
            print(f"OK {local.name} -> {remote} ({n} files)")
        for local, remote in UPLOAD_FILES:
            if not local.is_file():
                print(f"SKIP missing file {local}", file=sys.stderr)
                continue
            _ensure_remote_dir(sftp, "/".join(remote.split("/")[:-1]))
            sftp.put(str(local), remote)
            total += 1
            print(f"OK {local.name}")
    finally:
        sftp.close()

    compose = (
        f"cd {REMOTE_BASE}/ravenna-ide && "
        f"echo '{pwd}' | sudo -S docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml "
        "-f docker-compose.ravenna-home.yml build ravenna-home-api ravenna-home-web backend && "
        f"echo '{pwd}' | sudo -S docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml "
        "-f docker-compose.ravenna-home.yml up -d ravenna-home-api ravenna-home-web backend"
    )
    _, out, err = client.exec_command(compose, timeout=900)
    code = out.channel.recv_exit_status()
    print(out.read().decode())
    if code != 0:
        print(err.read().decode(), file=sys.stderr)
        client.close()
        return 1

    client.close()
    print(f"Deploy OK — {total} arquivos, stack reiniciada em {HOST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
