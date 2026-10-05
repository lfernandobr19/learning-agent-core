#!/usr/bin/env python3
"""Enable full Ravenna IDE on VM — workspaces, env, docker."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"
VM_DIR = "/home/<USER>/learning-agent"
HOST = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
USER = os.environ.get("RAVENNA_VM_USER", "<USER>")
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
ACCESS = "ravenna-vm"


def sudo(client, cmd, timeout=900):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    return stdout.read().decode("utf-8", errors="replace")


def docker_env(source: Path) -> str:
    skip = (
        "LEARNING_DB=", "LOCAL_BACKUP_DIR=", "RAVENNA_WORKSPACE", "CHAT_API_BASE=",
        "CHAT_MODEL=", "CHAT_MODEL_FAST=", "STUDENT_API_BASE=", "IDE_AGENT_USE_LOCAL=",
        "API_HOST=", "AUTO_AGENT_AUTONOMY=",
    )
    lines = [l for l in source.read_text(encoding="utf-8").splitlines() if not any(l.startswith(p) for p in skip)]
    lines.append("""
# --- VM full IDE ---
LEARNING_DB=/app/data
RAVENNA_WORKSPACE_ROOT=/app
RAVENNA_WORKSPACE_PARENT=/app
API_HOST=0.0.0.0
AUTO_AGENT_AUTONOMY=true
AUTONOMY_INTERVAL_SECONDS=1800
IDE_AGENT_USE_LOCAL=false
CLOUD_SYNC_ENABLED=false
AUTO_SYNC=false
CHAT_API_BASE=https://api.groq.com/openai/v1
CHAT_MODEL=llama-3.3-70b-versatile
CHAT_MODEL_FAST=llama-3.3-70b-versatile
STUDENT_API_BASE=https://api.groq.com/openai/v1
RAVENNA_PUBLIC_HOST=ravenna-vm
""")
    return "\n".join(lines)


def upload_tree(sftp, local: Path, remote: Path, rel_parts: tuple[str, ...]) -> None:
    target = local
    for part in rel_parts:
        target = target / part
    if target.is_file():
        text = target.read_text(encoding="utf-8").replace("\r\n", "\n")
        remote_file = f"{remote}/{'/'.join(rel_parts)}"
        parts = remote_file.rsplit("/", 1)
        try:
            sftp.stat(parts[0])
        except OSError:
            pass
        with sftp.file(remote_file, "w") as fh:
            fh.write(text)


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    client.connect(HOST, username=USER, password=PWD, timeout=30)

    sftp = client.open_sftp()
    # Patch code + compose
    for rel in (
        "learning_agent/core/workspace_roots.py",
        "ravenna-ide/docker-compose.yml",
    ):
        local = ROOT / rel.replace("/", os.sep)
        remote = f"{VM_DIR}/{rel}"
        text = local.read_text(encoding="utf-8").replace("\r\n", "\n")
        with sftp.file(remote, "w") as fh:
            fh.write(text)

    roots = (ROOT / "data/ide-workspace-roots.docker.json").read_text(encoding="utf-8")
    with sftp.file(f"{VM_DIR}/data/ide-workspace-roots.json", "w") as fh:
        fh.write(roots)

    with sftp.file(f"{VM_DIR}/.env", "w") as fh:
        fh.write(docker_env(ROOT / ".env"))

    with sftp.file(f"{COMPOSE}/.env", "w") as fh:
        fh.write(f"VITE_API_URL=http://{ACCESS}:8000\nVITE_WS_URL=ws://{ACCESS}:8000\n")
    sftp.close()

    out = sudo(client, f"cd {COMPOSE} && docker compose up -d --force-recreate backend")
    print(out.encode("ascii", errors="replace").decode("ascii"))
    print("Waiting for API...")
    stdin, stdout, _ = client.exec_command(
        "for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf http://127.0.0.1:8000/health && break; sleep 3; done",
        timeout=60,
    )
    health_raw = stdout.read().decode("utf-8", errors="replace")
    if health_raw.strip():
        h = json.loads(health_raw.strip().split("\n")[-1] if "\n" in health_raw else health_raw)
        print(f"notes={h['learning']['total_notes']} autonomy_env=true")

    for path in (
        "/api/workspace/roots",
        "/api/files?path=learning-agent",
    ):
        stdin, stdout, _ = client.exec_command(f"curl -sf 'http://127.0.0.1:8000{path}' | head -c 400", timeout=20)
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"{path}:", out[:200])

    client.close()
    print(f"\nIDE completa: http://{ACCESS}:5173")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
