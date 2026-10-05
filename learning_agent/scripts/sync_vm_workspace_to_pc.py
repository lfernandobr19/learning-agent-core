#!/usr/bin/env python3
"""Pull workspace edits VM -> PC (/home/<USER>/workspace-pc)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))
from bootstrap_ravenna_vm import find_host  # noqa: E402

PWD = os.environ.get("RAVENNA_VM_PASSWORD", "")
LOCAL = Path(os.environ.get("RAVENNA_PC_WORKSPACE", ROOT)).resolve()
REMOTE = os.environ.get("RAVENNA_VM_WORKSPACE", "/home/<USER>/workspace-pc")
USER = os.environ.get("RAVENNA_VM_USER", "<USER>")

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


def list_remote_files(sftp: paramiko.SFTPClient, remote: str, prefix: str = "") -> list[str]:
    out: list[str] = []
    for entry in sftp.listdir_attr(remote):
        name = entry.filename
        if name in (".", ".."):
            continue
        rpath = f"{remote}/{name}"
        rel = f"{prefix}/{name}" if prefix else name
        if stat.S_ISDIR(entry.st_mode):
            if name in SKIP_DIRS:
                continue
            out.extend(list_remote_files(sftp, rpath, rel))
        else:
            out.append(rel)
    return out


def download_tree(sftp: paramiko.SFTPClient, local: Path, remote: str) -> tuple[int, int]:
    files = 0
    skipped = 0
    for rel_str in list_remote_files(sftp, remote):
        rel = Path(rel_str)
        if should_skip(rel):
            skipped += 1
            continue
        rpath = f"{remote}/{rel.as_posix()}"
        lpath = local / rel
        lpath.parent.mkdir(parents=True, exist_ok=True)
        try:
            rstat = sftp.stat(rpath)
            if lpath.is_file() and lpath.stat().st_mtime >= rstat.st_mtime:
                skipped += 1
                continue
        except OSError:
            pass
        try:
            sftp.get(rpath, str(lpath))
        except (OSError, PermissionError) as exc:
            skipped += 1
            if files == 0 and skipped < 3:
                print(f"  skip {rel}: {exc}", flush=True)
            continue
        files += 1
        if files % 200 == 0:
            print(f"  ... {files} arquivos", flush=True)
    return files, skipped


def main() -> int:
    if not PWD:
        print("Defina RAVENNA_VM_PASSWORD", file=sys.stderr)
        return 1
    LOCAL.mkdir(parents=True, exist_ok=True)

    host = os.environ.get("RAVENNA_VM_HOST") or find_host()
    print(f"Pull {USER}@{host}:{REMOTE} -> {LOCAL}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=USER, password=PWD, timeout=30)
    sftp = client.open_sftp()
    try:
        n, skip = download_tree(sftp, LOCAL, REMOTE)
    finally:
        sftp.close()
    client.close()

    print(f"OK — {n} arquivos atualizados no PC ({skip} ignorados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
