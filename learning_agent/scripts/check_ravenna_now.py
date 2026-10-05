#!/usr/bin/env python3
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")  # required; never hardcode

if not PWD:

    raise SystemExit("Set RAVENNA_VM_PASSWORD in the environment (no hardcoded passwords).")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=15)
stdin, stdout, _ = c.exec_command(
    "curl -sf http://127.0.0.1:8000/health | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[\"learning\"][\"total_notes\"], d[\"status\"])'; "
    "sudo docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null || docker ps --format '{{.Names}} {{.Status}}'",
    timeout=30,
    get_pty=True,
)
stdin.write(PWD + "\n")
stdin.channel.shutdown_write()
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
