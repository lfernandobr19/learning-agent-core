#!/usr/bin/env python3
"""Sync PC workspace folder to VM for IDE remota (/app/pc-workspace)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))

from bootstrap_ravenna_vm import find_host  # noqa: E402

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")

# Fonte: ou um caminho Windows arbitrário (RAVENNA_PC_SYNC_SOURCE), ou uma subpasta
# do espelho padrão (RAVENNA_PC_WORKSPACE + RAVENNA_PC_SYNC_SUBFOLDER).
SOURCE = os.environ.get("RAVENNA_PC_SYNC_SOURCE", "").strip()
REMOTE_SUB = os.environ.get("RAVENNA_PC_SYNC_REMOTE_SUB", "").strip().strip("/").replace("\\", "/")
_LOCAL_BASE = Path(os.environ.get("RAVENNA_PC_WORKSPACE", ROOT)).resolve()
_SUBFOLDER = os.environ.get("RAVENNA_PC_SYNC_SUBFOLDER", "").strip().strip("/").replace("\\", "/")

if SOURCE:
    LOCAL = Path(SOURCE).resolve()
else:
    LOCAL = (_LOCAL_BASE / _SUBFOLDER).resolve() if _SUBFOLDER else _LOCAL_BASE

REMOTE_BASE = os.environ.get("RAVENNA_VM_WORKSPACE", "/home/lfernando/workspace-pc")
if SOURCE:
    REMOTE = f"{REMOTE_BASE}/{REMOTE_SUB}" if REMOTE_SUB else REMOTE_BASE
elif _SUBFOLDER:
    REMOTE = f"{REMOTE_BASE}/{_SUBFOLDER}"
else:
    REMOTE = REMOTE_BASE
USER = "lfernando"

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    ".venv312",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".cursor",
    "data",
    ".tmp.driveupload",
}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def should_skip(rel: Path) -> bool:
    if rel.suffix.lower() in SKIP_SUFFIXES:
        return True
    return bool(set(rel.parts) & SKIP_DIRS)


def upload_tree(sftp: paramiko.SFTPClient, local: Path, remote: str) -> tuple[int, int]:
    files = 0
    skipped = 0
    for path in local.rglob("*"):
        rel = path.relative_to(local)
        if should_skip(rel):
            skipped += 1
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
            parts = parent.split("/")
            cur = ""
            for part in parts:
                if not part:
                    continue
                cur = f"{cur}/{part}" if cur else part
                try:
                    sftp.stat(cur)
                except OSError:
                    sftp.mkdir(cur)
        sftp.put(str(path), rpath)
        files += 1
        if files % 200 == 0:
            print(f"  ... {files} arquivos", flush=True)
    return files, skipped


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1
    if not LOCAL.is_dir():
        print(f"Pasta local inexistente: {LOCAL}", file=sys.stderr)
        return 1

    host = os.environ.get("RAVENNA_VM_HOST") or find_host()
    print(f"Sync {LOCAL} -> {USER}@{host}:{REMOTE}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PWD, timeout=30)
    stdin, stdout, _ = client.exec_command(f"mkdir -p {REMOTE}", timeout=30)
    stdout.channel.recv_exit_status()

    sftp = client.open_sftp()
    try:
        n, skip = upload_tree(sftp, LOCAL, REMOTE)
    finally:
        sftp.close()
    client.close()

    print(f"OK — {n} arquivos enviados ({skip} ignorados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
