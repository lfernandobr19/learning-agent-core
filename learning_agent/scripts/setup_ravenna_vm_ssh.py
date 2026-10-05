#!/usr/bin/env python3
"""One-shot VM setup via SSH — strip desktop + remote access."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]


def run(client: paramiko.SSHClient, cmd: str, *, timeout: int = 180) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out, err


def sudo_file(client: paramiko.SSHClient, password: str, remote_path: str, *, timeout: int = 900) -> tuple[int, str]:
    stdin, stdout, stderr = client.exec_command(f"sudo -S bash {remote_path} 2>&1", timeout=timeout, get_pty=True)
    stdin.write(password + "\n")
    stdin.channel.shutdown_write()
    stdout.channel.settimeout(timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return stdout.channel.recv_exit_status(), out + err


def upload_script(client: paramiko.SSHClient, local: Path, remote: str) -> None:
    text = local.read_text(encoding="utf-8").replace("\r\n", "\n")
    sftp = client.open_sftp()
    with sftp.file(remote, "w") as fh:
        fh.write(text)
    sftp.chmod(remote, 0o755)
    sftp.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=args.password, timeout=25)

    strip_local = ROOT / "scripts/vm/debian-strip-desktop.sh"
    remote_local = ROOT / "scripts/vm/debian-remote-setup.sh"
    upload_script(client, strip_local, "/tmp/debian-strip-desktop.sh")
    upload_script(client, remote_local, "/tmp/debian-remote-setup.sh")

    code, out = sudo_file(client, args.password, "/tmp/debian-strip-desktop.sh", timeout=900)
    print("=== strip desktop ===", code)
    print(out[-5000:])

    code, out = sudo_file(client, args.password, "/tmp/debian-remote-setup.sh", timeout=300)
    print("=== remote setup ===", code)
    print(out[-3000:])

    code, out, err = run(client, "groups; systemctl get-default; systemctl is-active ssh; hostname -I")
    print("=== status ===")
    print(out or err)

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
