#!/usr/bin/env python3
"""Diagnóstico rápido do backend na VM."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(ROOT / ".env")
_load_dotenv(ROOT / "scripts" / "host-gpu.env")

import paramiko  # noqa: E402

pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
if not pwd:
    print("RAVENNA_VM_PASSWORD missing", file=sys.stderr)
    raise SystemExit(1)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=pwd, timeout=30)

COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"
cmds = [
    "docker ps -a --format '{{.Names}} {{.Status}}'",
    f"cd {COMPOSE} && docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml up -d backend 2>&1",
    "sleep 12",
    "docker ps -a --filter name=ravenna-backend --format '{{.Status}}'",
    "docker logs ravenna-backend 2>&1 | tail -25",
    "curl -sf http://127.0.0.1:8000/health | head -c 400",
]
for cmd in cmds:
    stdin, stdout, stderr = client.exec_command(
        f"echo {pwd!r} | sudo -S bash -c {cmd!r}",
        timeout=90,
        get_pty=True,
    )
    print(f"\n=== {cmd} ===")
    text = stdout.read().decode("utf-8", errors="replace")[-2500:]
    print(text.encode("ascii", errors="replace").decode())
client.close()
