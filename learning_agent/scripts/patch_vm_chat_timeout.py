#!/usr/bin/env python3
import os
import re
import paramiko
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")  # required; never hardcode
if not PWD:
    raise SystemExit("Set RAVENNA_VM_PASSWORD in the environment (no hardcoded passwords).")
VM_ENV = "/home/<USER>/learning-agent/.env"
COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=15)
sftp = c.open_sftp()
text = sftp.file(VM_ENV, "r").read().decode("utf-8")
text = re.sub(r"CHAT_MODEL_FAST=.*", "CHAT_MODEL_FAST=qwen2.5:7b", text)
if "CHAT_MODEL_FAST=" not in text:
    text += "\nCHAT_MODEL_FAST=qwen2.5:7b\n"
sftp.file(VM_ENV, "w").write(text)
sftp.close()
stdin, stdout, _ = c.exec_command(f"sudo bash -c 'cd {COMPOSE} && docker compose up -d --force-recreate backend'", timeout=120, get_pty=True)
stdin.write(PWD + "\n")
stdin.channel.shutdown_write()
stdout.read()
c.close()
print("patched CHAT_MODEL_FAST=qwen2.5:7b")
