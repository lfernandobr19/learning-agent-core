#!/usr/bin/env python3
"""Sync Ravenna Home MVP artifacts to VM (ravenna-home, agents, learning_agent, compose)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
USER = "lfernando"
REMOTE_ROOT = "/home/<USER>/learning-agent"

SYNC_DIRS = [
    ("ravenna-home", f"{REMOTE_ROOT}/ravenna-home"),
    ("agents", f"{REMOTE_ROOT}/agents"),
    ("learning_agent", f"{REMOTE_ROOT}/learning_agent"),
]

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache", "dist", "build", ".venv", ".venv312", "venv",
}


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
    host = os.environ.get("RAVENNA_VM_HOST", "ravenna-vm")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=pwd, timeout=30)
    sftp = client.open_sftp()
    total = 0
    try:
        for local_name, remote in SYNC_DIRS:
            local = ROOT / local_name
            if not local.is_dir():
                print(f"skip {local_name} (missing)")
                continue
            n = upload_tree(sftp, local, remote)
            print(f"sync {local_name}: {n} files")
            total += n
        compose_local = ROOT / "ravenna-ide" / "docker-compose.host-gpu.yml"
        compose_remote = f"{REMOTE_ROOT}/ravenna-ide/docker-compose.host-gpu.yml"
        with sftp.file(compose_remote, "w") as fh:
            fh.write(compose_local.read_text(encoding="utf-8").replace("\r\n", "\n"))
    finally:
        sftp.close()

    cmds = [
        f"cd {REMOTE_ROOT}/ravenna-ide && docker compose -f docker-compose.yml -f docker-compose.host-gpu.yml up -d --force-recreate backend",
        "docker exec ravenna-backend pip install -q -r /app/ravenna-home/backend/requirements.txt pytest",
        "docker exec ravenna-backend bash -c 'cd /app/ravenna-home/backend && python -m pytest tests/ -q'",
    ]
    for cmd in cmds:
        print(">", cmd[:80])
        _, o, e = client.exec_command(cmd, timeout=300)
        out = o.read().decode()
        code = o.channel.recv_exit_status()
        print(out[-1500:])
        if code != 0 and "pytest" in cmd:
            print(e.read().decode()[-500:], file=sys.stderr)
            client.close()
            return 1
    client.close()
    print(f"OK — {total} arquivos sincronizados, backend validado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
