#!/usr/bin/env python3
"""Find Ravenna VM and bring up Docker stack."""
import json
import os
import re
import socket
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"
VM_ENV = "/home/<USER>/learning-agent/.env"
USER = "lfernando"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
ACCESS = "ravenna-vm"
CANDIDATES = [
    "ravenna-vm",
    "<TAILSCALE_IP_4>",
    "172.23.125.87",
] + [f"172.23.125.{i}" for i in range(80, 95)] + [f"172.23.112.{i}" for i in range(2, 30)]


def port_open(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    try:
        if not re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
            host = socket.gethostbyname(host)
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


def find_host() -> str:
    for h in CANDIDATES:
        if port_open(h):
            print(f"SSH open: {h}")
            return h
    raise SystemExit("VM não encontrada na rede (porta 22).")


def sudo(client, cmd, timeout=600):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    return stdout.read().decode("utf-8", errors="replace")


def docker_env(source_env: Path) -> str:
    skip = ("LEARNING_DB=", "LOCAL_BACKUP_DIR=", "RAVENNA_WORKSPACE", "CHAT_API_BASE=", "CHAT_MODEL=",
            "CHAT_MODEL_FAST=", "STUDENT_API_BASE=", "IDE_AGENT_USE_LOCAL=", "API_HOST=")
    lines = [l for l in source_env.read_text(encoding="utf-8").splitlines() if not any(l.startswith(p) for p in skip)]
    lines.append(f"""
# --- VM Docker ---
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
RAVENNA_PUBLIC_HOST={ACCESS}
""")
    return "\n".join(lines)


def main() -> int:
    host = find_host()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PWD, timeout=25)

    sftp = client.open_sftp()
    with sftp.file(VM_ENV, "w") as f:
        f.write(docker_env(ROOT / ".env"))
    with sftp.file(f"{COMPOSE}/.env", "w") as f:
        f.write(f"VITE_API_URL=http://{ACCESS}:8000\nVITE_WS_URL=ws://{ACCESS}:8000\n")
    sftp.close()

    print(sudo(client, f"cd {COMPOSE} && docker compose up -d", timeout=900)[-2000:])
    stdin, stdout, _ = client.exec_command("curl -sf http://127.0.0.1:8000/health", timeout=30)
    health = json.loads(stdout.read().decode())
    notes = health.get("learning", {}).get("total_notes")
    print(f"status={health.get('status')} notes={notes}")

    _, ts, _ = client.exec_command("tailscale ip -4 2>/dev/null; tailscale status 2>/dev/null | head -3")
    print("tailscale:", ts.read().decode().strip())

    client.close()
    print(f"\nIDE: http://{ACCESS}:5173  (Tailscale logado neste PC)")
    print(f"LAN: http://{host}:5173")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
