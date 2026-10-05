#!/usr/bin/env python3
import json
import os
import paramiko

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username="lfernando", password=PWD, timeout=20)
for path in (
    "/app/data/remote-servers.json",
    "/app/data/ide-workspace-roots.json",
):
    cmd = f"docker exec ravenna-backend cat {path}"
    _, o, _ = c.exec_command(cmd, timeout=30)
    print(f"=== {path} ===")
    print(o.read().decode()[:2500])
c.close()
