#!/usr/bin/env python3
"""Re-run docker compose build on VM after Dockerfile fix."""
import os
import paramiko
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST, USER = "172.26.235.186", "<USER>"
PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
COMPOSE = "/home/<USER>/learning-agent/ravenna-ide"


def sudo(client, cmd, timeout=7200):
    stdin, stdout, _ = client.exec_command(
        f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True
    )
    stdin.write(PWD + "\n")
    stdin.channel.shutdown_write()
    out = stdout.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out


def main():
    if not PWD:
        raise SystemExit("Defina RAVENNA_VM_PASSWORD")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PWD, timeout=30)

    uploads = [
        (ROOT / "ravenna-ide/Dockerfile.frontend", f"{COMPOSE}/Dockerfile.frontend"),
        (ROOT / "ravenna-ide/docker-compose.yml", f"{COMPOSE}/docker-compose.yml"),
        (ROOT / ".dockerignore", f"/home/<USER>/learning-agent/.dockerignore"),
    ]
    sftp = client.open_sftp()
    for local, remote in uploads:
        text = local.read_text(encoding="utf-8").replace("\r\n", "\n")
        with sftp.file(remote, "w") as fh:
            fh.write(text)
    sftp.close()

    code, out = sudo(
        client,
        f"cd {COMPOSE} && docker compose build --progress=plain && docker compose up -d",
    )
    print("BUILD EXIT", code)
    print(out[-15000:])

    _, health = sudo(client, "curl -sf http://127.0.0.1:8000/health; echo; docker ps")
    print("HEALTH", health)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
