"""Anexos — upload seguro + indexação RAG (Fase 4)."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR
from learning_agent.core import knowledge

ATTACHMENTS_DIR = DATA_DIR / "attachments"
MAX_ATTACHMENT_BYTES = 5_000_000
ALLOWED_EXTENSIONS = {
    ".txt",
    ".md",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".sql",
    ".csv",
    ".log",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_EXTENSIONS = ALLOWED_EXTENSIONS - {".csv"} - IMAGE_EXTENSIONS


class AttachmentError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-]", "_", base, flags=re.ASCII)
    return cleaned[:120] or "anexo"


def save_attachment(filename: str, content: bytes) -> dict[str, Any]:
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(
            f"Arquivo muito grande (máx {MAX_ATTACHMENT_BYTES // 1_000_000} MB)",
            status_code=413,
        )

    safe = _safe_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentError(
            f"Extensão não permitida: {ext or '(sem extensão)'}",
            status_code=415,
        )

    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:8]
    stored_name = f"{stamp}-{uid}-{safe}"
    path = ATTACHMENTS_DIR / stored_name
    path.write_bytes(content)

    indexed = False
    rag_id: str | None = None
    if ext in TEXT_EXTENSIONS:
        try:
            text = content.decode("utf-8")
            title = f"Anexo: {safe}"
            rag = knowledge.index_text(
                title,
                text,
                tags=["attachment", "upload", "ravenna-ide", ext.lstrip(".")],
            )
            knowledge.add_note(
                f"[Anexo] {safe}",
                text[:8000],
                tags=["anexo", "upload", "rag", "ravenna-ide"],
            )
            indexed = True
            rag_id = rag.get("id")
        except UnicodeDecodeError:
            pass

    return {
        "id": stored_name,
        "filename": safe,
        "stored_path": str(path.relative_to(DATA_DIR)),
        "size": len(content),
        "indexed": indexed,
        "rag_id": rag_id,
        "is_image": ext in IMAGE_EXTENSIONS,
        "url": f"/api/attachments/{stored_name}/file",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_attachment_path(attachment_id: str) -> Path:
    safe = Path(attachment_id).name
    if not safe or safe != attachment_id:
        raise AttachmentError("ID inválido", status_code=400)
    path = ATTACHMENTS_DIR / safe
    if not path.is_file():
        raise AttachmentError("Anexo não encontrado", status_code=404)
    return path


def list_attachments(limit: int = 40) -> list[dict[str, Any]]:
    if not ATTACHMENTS_DIR.exists():
        return []
    files = sorted(ATTACHMENTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        if not path.is_file():
            continue
        stat = path.stat()
        out.append(
            {
                "id": path.name,
                "filename": path.name.split("-", 2)[-1] if "-" in path.name else path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out
