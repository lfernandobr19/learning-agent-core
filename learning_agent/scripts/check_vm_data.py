#!/usr/bin/env python3
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
if not PWD:
    raise SystemExit("Defina RAVENNA_VM_PASSWORD")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("172.26.235.186", username="lfernando", password=PWD, timeout=30)

cmds = [
    "ls -lh /home/lfernando/learning-agent/data/*.db 2>/dev/null | head -10",
    "du -sh /home/lfernando/learning-agent/data/chroma 2>/dev/null",
    "grep LEARNING_DB /home/lfernando/learning-agent/.env",
    "sudo docker exec ravenna-backend ls -lh /app/data/*.db 2>/dev/null | head -5",
    "sudo docker exec ravenna-backend python3 -c \"from pathlib import Path; import os; print('LEARNING_DB', os.environ.get('LEARNING_DB')); p=Path('/app/data'); print('dbs', list(p.glob('*.db'))[:5])\"",
    "curl -sf http://127.0.0.1:8000/health | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d.get('learning'))\"",
]
for cmd in cmds:
    print("===", cmd[:70], "===")
    stdin, stdout, _ = c.exec_command(cmd, timeout=90, get_pty=True)
    if "sudo" in cmd:
        stdin.write(PWD + "\n")
        stdin.channel.shutdown_write()
    print(stdout.read().decode("utf-8", errors="replace")[:1500])
c.close()
