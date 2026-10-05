#!/usr/bin/env python3
import paramiko
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")  # required; never hardcode
if not PWD:
    raise SystemExit("Set RAVENNA_VM_PASSWORD in the environment (no hardcoded passwords).")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=15)
py = r'''
import os, traceback
from learning_agent.core import llm
msgs=[{"role":"user","content":"diga ok"}]
try:
    r,m=llm.chat_with_fallback(msgs, max_tokens=20)
    print("OK", m, r[:80])
except Exception as e:
    print("FAIL", e)
    traceback.print_exc()
try:
    r,m=llm.chat_complete(msgs, max_tokens=20)
    print("direct OK", m, r[:80])
except Exception as e:
    print("direct FAIL", e)
'''
stdin, stdout, stderr = c.exec_command(
    f"sudo docker exec ravenna-backend python3 -c {repr(py)}",
    timeout=300,
    get_pty=True,
)
stdin.write(PWD + "\n")
stdin.channel.shutdown_write()
print(stdout.read().decode("utf-8", errors="replace"))
print(stderr.read().decode("utf-8", errors="replace"))
c.close()
