#!/usr/bin/env python3
"""Sync local ravenna-home/ to VM and ensure docker bind mount."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "ravenna-home"
REMOTE = "/home/<USER>/learning-agent/ravenna-home"
COMPOSE_REMOTE = "/home/<USER>/learning-agent/ravenna-ide/docker-compose.host-gpu.yml"
COMPOSE_LOCAL = ROOT / "ravenna-ide" / "docker-compose.host-gpu.yml"
USER = "lfernando"

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}


def should_skip(rel: Path) -> bool:
    return bool(set(rel.parts) & SKIP_DIRS)


def upload_tree(sftp: paramiko.SFTPClient, local: Path, remote: str) -> int:
    count = 0
    for path in sorted(local.rglob("*")):
        rel = path.relative_to(local)
        if should_skip(rel):
            continue
        rpath = f"{remote}/{rel.as_posix()}"
        if path.is_dir():
            try:
                sftp.stat(rpath)
            except OSError:
                sftp.mkdir(rpath)
            continue
        parent = "/".join(rpath.split("/")[:-1])
        try:
            sftp.stat(parent)
        except OSError:
            cur = ""
            for part in parent.split("/"):
                if not part:
                    continue
                cur = f"{cur}/{part}" if cur else part
                try:
                    sftp.stat(cur)
                except OSError:
                    sftp.mkdir(cur)
        sftp.put(str(path), rpath)
        count += 1
    return count


def main() -> int:
    pwd = os.environ.get("RAVENNA_VM_PASSWORD", "")
    if not pwd:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1
    if not LOCAL.is_dir():
        print(f"Pasta local inexistente: {LOCAL}", file=sys.stderr)
        return 1

    host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
    print(f"Sync {LOCAL} -> {USER}@{host}:{REMOTE}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=pwd, timeout=30)
    _, out, _ = client.exec_command(f"mkdir -p {REMOTE}", timeout=30)
    out.channel.recv_exit_status()

    sftp = client.open_sftp()
    try:
        n = upload_tree(sftp, LOCAL, REMOTE)
        with sftp.file(COMPOSE_REMOTE, "w") as fh:
            fh.write(COMPOSE_LOCAL.read_text(encoding="utf-8").replace("\r\n", "\n"))
    finally:
        sftp.close()

    recreate = (
        "cd /home/<USER>/learning-agent/ravenna-ide && "
        "docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml up -d --force-recreate backend"
    )
    _, out, err = client.exec_command(recreate, timeout=180)
    code = out.channel.recv_exit_status()
    print(out.read().decode())
    if code != 0:
        print(err.read().decode(), file=sys.stderr)
        client.close()
        return 1

    verify = (
        "docker exec ravenna-backend ls -la /app/ravenna-home/backend/main.py "
        "&& docker exec ravenna-backend python -c "
        "\"from pathlib import Path; p=Path('/app/ravenna-home'); "
        "print('ok', p.is_dir(), (p/'backend'/'main.py').is_file())\""
    )
    _, out, err = client.exec_command(verify, timeout=60)
    print(out.read().decode())
    if out.channel.recv_exit_status() != 0:
        print(err.read().decode(), file=sys.stderr)
        client.close()
        return 1

    client.close()
    print(f"OK — {n} arquivos sincronizados, mount /app/ravenna-home ativo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
