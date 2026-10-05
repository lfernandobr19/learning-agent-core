#!/usr/bin/env python3
import os
import sys
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
HOST = os.environ.get("RAVENNA_VM_HOST", "172.23.125.87")
if not PWD:
    sys.exit("Defina RAVENNA_VM_PASSWORD")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="lfernando", password=PWD, timeout=20)
for cmd in (
    "free -m",
    "docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo no-docker",
    "curl -sf -m 8 http://127.0.0.1:8000/health 2>/dev/null | head -c 300 || echo health-down",
    "curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:5173/ 2>/dev/null || echo frontend-down",
):
    _, out, err = c.exec_command(cmd, timeout=30)
    print(f"=== {cmd.split()[0]} ===")
    print(out.read().decode("utf-8", errors="replace"))
c.close()
