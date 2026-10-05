#!/usr/bin/env python3
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username="lfernando", password=PWD, timeout=30)
cmd = (
    "grep -E 'EVOLUTION_LIGHT|AUTO_PROOFS|AGENT_STUDY' "
    "/home/lfernando/learning-agent/.env 2>/dev/null; "
    "test -f /home/lfernando/learning-agent/data/autonomous_evolution_last.json "
    "&& tail -8 /home/lfernando/learning-agent/data/autonomous_evolution_last.json"
)
_, o, _ = c.exec_command(cmd, timeout=20)
print(o.read().decode("utf-8", "replace"))
c.close()
