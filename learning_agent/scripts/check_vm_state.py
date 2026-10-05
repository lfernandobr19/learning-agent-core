#!/usr/bin/env python3
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
if not PWD:
    raise SystemExit("Defina RAVENNA_VM_PASSWORD")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("172.26.235.186", username="lfernando", password=PWD, timeout=30)
stdin, stdout, stderr = c.exec_command(
    "ls -la /home/lfernando/learning-agent/.env 2>/dev/null; "
    "du -sh /home/lfernando/learning-agent 2>/dev/null; "
    "ls -lh /tmp/learning-agent-full.tar.gz 2>/dev/null; "
    "tailscale ip -4; "
    "sudo docker ps --format '{{.Names}} {{.Status}}'",
    timeout=60,
    get_pty=True,
)
stdin.write(PWD + "\n")
stdin.channel.shutdown_write()
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
