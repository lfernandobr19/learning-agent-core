#!/usr/bin/env python3
import os
import sys
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
HOST = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
if not PWD:
    sys.exit("Defina RAVENNA_VM_PASSWORD")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="lfernando", password=PWD, timeout=20)

checks = [
    ("docker", "docker ps --format '{{.Names}}|{{.Status}}'"),
    ("telegram_proc", "pgrep -af 'telegram|run_telegram' || echo NONE"),
    ("health", "curl -sf -m 8 http://127.0.0.1:8000/health"),
]
for name, cmd in checks:
    _, out, err = c.exec_command(cmd, timeout=30)
    text = out.read().decode("utf-8", errors="replace").strip()
    print(f"=== {name} ===")
    print(text[:1200] if text else err.read().decode("utf-8", errors="replace")[:400])
c.close()
