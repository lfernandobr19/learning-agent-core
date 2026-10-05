#!/usr/bin/env python3
"""SSH key, limpar data duplicada, reiniciar backend."""
from __future__ import annotations

import os
import sys

import paramiko

VM_DIR = "/home/<USER>/learning-agent"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
HOST = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")


def sudo(client, cmd, timeout=120):
    stdin, stdout, _ = client.exec_command(
        f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True
    )
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=os.environ.get("RAVENNA_VM_USER", "<USER>"), password=PWD, timeout=30)

    client.exec_command("mkdir -p /home/<USER>/.ssh && chmod 700 /home/<USER>/.ssh")
    _, o, _ = client.exec_command(
        "test -f /home/<USER>/.ssh/ravenna_pc.pub && echo yes || echo no", timeout=15
    )
    if "yes" not in o.read().decode():
        _, o, e = client.exec_command(
            "ssh-keygen -t ed25519 -N '' -f /home/<USER>/.ssh/ravenna_pc -q",
            timeout=60,
        )
        o.channel.recv_exit_status()

    _, o, _ = client.exec_command("cat /home/<USER>/.ssh/ravenna_pc.pub", timeout=15)
    pub = o.read().decode("utf-8").strip()
    print("PUBKEY:", pub)

    code, out = sudo(client, "rm -rf /home/<USER>/workspace-pc/data && echo CLEANED")
    print("clean data:", code, out.strip()[-80:])

    code, out = sudo(
        client, f"cd {VM_DIR}/ravenna-ide && docker compose restart backend", timeout=120
    )
    print("restart:", code, out[-200:].encode("ascii", errors="replace").decode())

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
