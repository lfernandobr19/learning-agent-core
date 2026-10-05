#!/usr/bin/env python3
"""Fix VM .env paths and restart Ravenna Docker."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"
VM_ENV = "/home/<USER>/learning-agent/.env"
USER = "lfernando"
HOST = os.environ.get("RAVENNA_VM_HOST", "")
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
ACCESS_HOST = "ravenna-vm"


def docker_env_for_vm(public_host: str, source_env: Path) -> str:
    lines: list[str] = []
    skip_prefixes = (
        "LEARNING_DB=",
        "LOCAL_BACKUP_DIR=",
        "RAVENNA_WORKSPACE",
        "CHAT_API_BASE=",
        "CHAT_MODEL=",
        "CHAT_MODEL_FAST=",
        "STUDENT_API_BASE=",
        "IDE_AGENT_USE_LOCAL=",
        "API_HOST=",
    )
    for raw in source_env.read_text(encoding="utf-8").splitlines():
        if any(raw.startswith(p) for p in skip_prefixes):
            continue
        lines.append(raw)

    overrides = f"""
# --- VM Docker (Tailscale: {public_host}) ---
LEARNING_DB=/app/data
API_HOST=0.0.0.0
CLOUD_SYNC_ENABLED=false
AUTO_SYNC=false
AUTO_AGENT_AUTONOMY=false
IDE_AGENT_USE_LOCAL=false
CHAT_API_BASE=https://api.groq.com/openai/v1
CHAT_MODEL=llama-3.3-70b-versatile
CHAT_MODEL_FAST=llama-3.3-70b-versatile
STUDENT_API_BASE=https://api.groq.com/openai/v1
RAVENNA_PUBLIC_HOST={public_host}
"""
    return "\n".join(lines) + overrides


def sudo(client, cmd, timeout=300):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    return stdout.read().decode("utf-8", errors="replace")


def resolve_host() -> str:
    if HOST:
        return HOST
    sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))
    from bootstrap_ravenna_vm import find_host

    return find_host()


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    host = resolve_host()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PWD, timeout=30)

    env_text = docker_env_for_vm(ACCESS_HOST, ROOT / ".env")
    sftp = client.open_sftp()
    with sftp.file(VM_ENV, "w") as fh:
        fh.write(env_text)
    compose_env = (
        f"VITE_API_URL=http://{ACCESS_HOST}:8000\n"
        f"VITE_WS_URL=ws://{ACCESS_HOST}:8000\n"
    )
    with sftp.file(f"{COMPOSE}/.env", "w") as fh:
        fh.write(compose_env)
    sftp.close()

    print(sudo(client, f"cd {COMPOSE} && docker compose up -d --force-recreate"))
    print(sudo(client, "sleep 10 && curl -sf http://127.0.0.1:8000/health"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
