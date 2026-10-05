#!/usr/bin/env python3
"""Pull ravenna-home + motor files from bare-metal ravenna → local workspace."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("RAVENNA_HOST", "<RAVENNA_TAILSCALE_IP>")
USER = os.environ.get("RAVENNA_VM_USER", "<USER>")
REMOTE_BASE = "/home/<USER>/learning-agent"

PULL_PATHS = [
    "ravenna-home/backend/main.py",
    "ravenna-home/backend/host_control.py",
    "ravenna-home/backend/pc_status.py",
    "ravenna-home/backend/homeassistant.py",
    "ravenna-home/backend/.env.example",
    "ravenna-home/frontend/src/App.tsx",
    "ravenna-home/frontend/src/api.ts",
    "ravenna-home/frontend/src/auth.tsx",
    "ravenna-home/frontend/src/components/Chat.tsx",
    "ravenna-home/frontend/src/components/GpuStatus.tsx",
    "ravenna-home/frontend/src/components/Lights.tsx",
    "ravenna-home/frontend/src/components/Scenes.tsx",
    "ravenna-home/frontend/public/manifest.json",
    "ravenna-home/frontend/index.html",
    "learning_agent/core/chat.py",
    "learning_agent/core/agent_tools.py",
    "learning_agent/core/ravenna_home_remote_ops.py",
    "ravenna-ide/docker-compose.ravenna-home.yml",
    "agents/projects/ravenna-home/manifest.yaml",
]


def main() -> int:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("RAVENNA_VM_PASSWORD="):
                pwd = line.split("=", 1)[1]
                break
    if not pwd:
        print("RAVENNA_VM_PASSWORD missing", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=pwd, timeout=30, allow_agent=True, look_for_keys=True)
    sftp = client.open_sftp()
    n = 0
    try:
        for rel in PULL_PATHS:
            remote = f"{REMOTE_BASE}/{rel.replace(chr(92), '/')}"
            local = ROOT / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                sftp.get(remote, str(local))
                n += 1
                print(f"OK {rel}")
            except OSError as exc:
                print(f"SKIP {rel}: {exc}", file=sys.stderr)
    finally:
        sftp.close()
        client.close()
    print(f"Pulled {n} files from {HOST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
