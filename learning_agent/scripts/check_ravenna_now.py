#!/usr/bin/env python3
import paramiko

PWD = "#Lalaloopsy5201."
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username="lfernando", password=PWD, timeout=15)
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
