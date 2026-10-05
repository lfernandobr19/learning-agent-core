#!/usr/bin/env python3
import re
import paramiko
PWD = "#Lalaloopsy5201."
VM_ENV = "/home/lfernando/learning-agent/.env"
COMPOSE = "/home/lfernando/learning-agent/ravenna-ide"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("ravenna-vm", username="lfernando", password=PWD, timeout=15)
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
