#!/usr/bin/env python3
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
if not PWD:
    raise SystemExit("Defina RAVENNA_VM_PASSWORD")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("172.26.235.186", username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=30)
for cmd in [
    "cat /home/<USER>/learning-agent/ravenna-ide/.env",
    "sudo docker ps --format '{{.Names}} {{.Status}}'",
    "tailscale status 2>/dev/null | head -8",
    "curl -sf http://127.0.0.1:5173/ | head -c 200",
    "sudo docker exec ravenna-frontend sh -c 'grep -o \"http[^\\\"]*8000\" /app/dist/assets/index*.js 2>/dev/null | head -3'",
]:
    print("===", cmd[:60], "===")
    stdin, stdout, _ = c.exec_command(cmd, timeout=60, get_pty=True)
    if "sudo" in cmd:
        stdin.write(PWD + "\n")
        stdin.channel.shutdown_write()
    print(stdout.read().decode("utf-8", errors="replace")[:800])
c.close()
