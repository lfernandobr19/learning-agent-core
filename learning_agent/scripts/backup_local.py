"""Backup local do learning-agent para pasta sincronizada (OneDrive / Google Drive)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import CHROMA_PATH, DATA_DIR, PROJECT_ROOT, SQLITE_PATH

BACKUP_MANIFEST = "backup_manifest.json"
KEEP_DEFAULT = 7

# Arquivos JSON de estado úteis para restaurar contexto operacional
STATE_GLOBS = (
    "finance_lead_*.json",
    "model_parity.json",
    "raven_readiness.json",
    "l6_refinement_last.json",
    "vast_credit_state.json",
)


def resolve_backup_root(explicit: str | None = None) -> Path:
    """Pasta destino: LOCAL_BACKUP_DIR ou OneDrive/Google Drive/Ravenna/learning-agent-backup."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("LOCAL_BACKUP_DIR", "").strip()
    if env:
        return Path(env).expanduser()

    home = Path.home()
    candidates = [
        Path("G:/Meu Drive/RAVENNA/learning-agent-backup"),
        home / "OneDrive" / "Ravenna" / "learning-agent-backup",
        home / "Google Drive" / "Ravenna" / "learning-agent-backup",
        home / "Google Drive" / "My Drive" / "Ravenna" / "learning-agent-backup",
        home / "Meu Drive" / "Ravenna" / "learning-agent-backup",
    ]
    for path in candidates:
        parent = path.parent.parent  # .../Ravenna or drive root
        if parent.exists():
            return path
    return home / "OneDrive" / "Ravenna" / "learning-agent-backup"


def _hot_sqlite_backup(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    with sqlite3.connect(str(src)) as source, sqlite3.connect(str(dest)) as target:
        source.backup(target)


def _copy_state_jsons(dest_data: Path) -> list[str]:
    copied: list[str] = []
    dest_data.mkdir(parents=True, exist_ok=True)
    for pattern in STATE_GLOBS:
        for path in sorted(DATA_DIR.glob(pattern)):
            if not path.is_file():
                continue
            target = dest_data / path.name
            shutil.copy2(path, target)
            copied.append(path.name)
    return copied


def _prune_old_backups(root: Path, keep: int) -> list[str]:
    if keep <= 0:
        return []
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.startswith("20")),
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[str] = []
    for old in dirs[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed.append(old.name)
    return removed


def run_local_backup(
    *,
    dest_root: str | Path | None = None,
    keep: int | None = None,
) -> dict[str, Any]:
    """Copia SQLite (hot backup), Chroma e JSONs de estado para pasta do Drive."""
    root = resolve_backup_root(str(dest_root) if dest_root else None)
    keep_n = keep if keep is not None else int(os.environ.get("LOCAL_BACKUP_KEEP", str(KEEP_DEFAULT)))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = root / stamp
    dest_data = dest / "data"
    dest_data.mkdir(parents=True, exist_ok=True)

    if not SQLITE_PATH.is_file():
        return {"success": False, "message": f"SQLite não encontrado: {SQLITE_PATH}"}

    db_dest = dest_data / "learning.db"
    _hot_sqlite_backup(SQLITE_PATH, db_dest)

    chroma_dest = dest_data / "chroma"
    if CHROMA_PATH.is_dir():
        shutil.copytree(CHROMA_PATH, chroma_dest, dirs_exist_ok=True)

    state_files = _copy_state_jsons(dest_data)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(PROJECT_ROOT),
        "sqlite_bytes": db_dest.stat().st_size,
        "chroma": CHROMA_PATH.is_dir(),
        "state_files": state_files,
        "cloud_sync": "local-only (Drive folder sync)",
    }
    (dest / BACKUP_MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    removed = _prune_old_backups(root, keep_n)
    return {
        "success": True,
        "message": f"Backup em {dest}",
        "dest": str(dest),
        "root": str(root),
        "sqlite_mb": round(db_dest.stat().st_size / 1024 / 1024, 2),
        "state_files": state_files,
        "pruned": removed,
        "keep": keep_n,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Backup local → OneDrive/Google Drive")
    parser.add_argument("--dest", default="", help="Pasta raiz de backup (override LOCAL_BACKUP_DIR)")
    parser.add_argument("--keep", type=int, default=0, help=f"Retenção (default {KEEP_DEFAULT})")
    args = parser.parse_args()
    result = run_local_backup(
        dest_root=args.dest or None,
        keep=args.keep if args.keep > 0 else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
