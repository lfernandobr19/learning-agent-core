#!/usr/bin/env python3
"""Rebuild only frontend on VM (Tailscale API URL)."""
import paramiko

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
COMPOSE = "/home/lfernando/learning-agent/ravenna-ide"
HOST, USER = "172.26.235.186", "lfernando"
PWD = __import__("os").environ.get("RAVENNA_VM_PASSWORD", "")
ACCESS = "ravenna-vm"


def sudo(client, cmd, timeout=1800):
    stdin, stdout, _ = client.exec_command(f"sudo -S bash -c {repr(cmd)}", timeout=timeout, get_pty=True)
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
    sftp = client.open_sftp()
    with sftp.file(f"{COMPOSE}/.env", "w") as fh:
        fh.write(f"VITE_API_URL=http://{ACCESS}:8000\nVITE_WS_URL=ws://{ACCESS}:8000\n")
    text = (ROOT / "ravenna-ide/Dockerfile.frontend").read_text(encoding="utf-8").replace("\r\n", "\n")
    with sftp.file(f"{COMPOSE}/Dockerfile.frontend", "w") as fh:
        fh.write(text)
    sftp.close()
    code, out = sudo(
        client,
        f"cd {COMPOSE} && docker compose build --no-cache frontend && docker compose up -d frontend",
    )
    print("EXIT", code, out[-4000:])
    _, health = sudo(client, "curl -sf http://127.0.0.1:8000/health | python3 -c 'import sys,json; print(json.load(sys.stdin)[\"learning\"][\"total_notes\"])'")
    print("notes", health)
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
