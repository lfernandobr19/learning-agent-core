#!/usr/bin/env python3
"""Configura SSH live VM->PC + perfil remoto na Ravenna."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
VM_DIR = "/home/<USER>/learning-agent"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
GPU_HOST = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")
PC_USER = os.environ.get("RAVENNA_PC_SSH_USER", "lfern")
PC_PATH = os.environ.get(
    "RAVENNA_PC_WORKSPACE",
    r"C:/Users/lfern/RAVENNA/learning-agent/learning-agent",
).replace("\\", "/")


def sudo(client, cmd, timeout=120):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=30)

    key_path = "/home/<USER>/.ssh/ravenna_pc"
    _, o, _ = client.exec_command(f"test -f {key_path} && echo yes || echo no", timeout=15)
    if "yes" not in o.read().decode():
        sudo(client, f"mkdir -p /home/<USER>/.ssh && chmod 700 /home/<USER>/.ssh")
        sudo(client, f"ssh-keygen -t ed25519 -N '' -f {key_path} -q", timeout=60)
        sudo(client, f"chown lfernando:lfernando {key_path} {key_path}.pub", timeout=30)

    _, o, _ = client.exec_command(f"cat {key_path}.pub", timeout=15)
    pub = o.read().decode("utf-8").strip()
    print("VM pubkey (primeiros 60 chars):", pub[:60])

    store = {
        "version": 1,
        "active_terminal_id": "pc-live",
        "profiles": [
            {
                "id": "pc-live",
                "label": "PC Luis (live SSH)",
                "host": GPU_HOST,
                "port": 22,
                "user": PC_USER,
                "identity_file": "/root/.ssh/ravenna_pc",
                "remote_path": PC_PATH,
                "use_remote_terminal": True,
            }
        ],
        "recents": [],
    }
    sftp = client.open_sftp()
    with sftp.file(f"{VM_DIR}/data/remote-servers.json", "w") as fh:
        fh.write(json.dumps(store, indent=2, ensure_ascii=False))
    sftp.close()

    client.close()
    print("remote-servers.json gravado na VM")
    print("PROXIMO: Admin no PC -> setup-pc-ssh-live.ps1 com pubkey:")
    print(pub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
