"""Mídia do chat mobile — imagens, vídeos e arquivos (upload + pull Windows)."""

from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from learning_agent.config import DATA_DIR

CHAT_MEDIA_DIR = DATA_DIR / "chat_media"
MAX_PHONE_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB por upload do celular
CHUNK_SIZE = 1024 * 1024  # 1 MB streaming

ALLOWED_UPLOAD_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp4",
    ".webm",
    ".mov",
    ".pdf",
    ".txt",
    ".md",
    ".zip",
}


class ChatMediaError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-]", "_", base, flags=re.ASCII)
    return cleaned[:120] or "arquivo"


def _media_type_for(ext: str, mime: str | None = None) -> str:
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if ext in {".mp4", ".webm", ".mov", ".avi", ".mkv"}:
        return "video"
    return "file"


def media_public_url(media_id: str) -> str:
    return f"/api/chat/media/{media_id}"


def save_media(content: bytes, filename: str, *, source: str = "upload") -> dict[str, Any]:
    if len(content) > MAX_PHONE_UPLOAD_BYTES:
        raise ChatMediaError(
            f"Arquivo muito grande (máx {MAX_PHONE_UPLOAD_BYTES // (1024 * 1024)} MB no celular)",
            status_code=413,
        )
    safe = _safe_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext and ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ChatMediaError(f"Extensão não permitida: {ext}", status_code=415)

    CHAT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:10]
    stored_name = f"{stamp}-{uid}-{safe}"
    path = CHAT_MEDIA_DIR / stored_name
    path.write_bytes(content)

    mime = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    media_type = _media_type_for(ext, mime)
    return {
        "id": stored_name,
        "filename": safe,
        "size": len(content),
        "mime": mime,
        "type": media_type,
        "source": source,
        "url": media_public_url(stored_name),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def save_media_stream(chunks: Iterator[bytes], filename: str, *, source: str = "windows") -> dict[str, Any]:
    """Grava stream sem limite de tamanho (pull do Windows → ravenna)."""
    safe = _safe_filename(filename)
    ext = Path(safe).suffix.lower()
    CHAT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uid = uuid.uuid4().hex[:10]
    stored_name = f"{stamp}-{uid}-{safe}"
    path = CHAT_MEDIA_DIR / stored_name

    total = 0
    with path.open("wb") as fh:
        for chunk in chunks:
            if not chunk:
                continue
            fh.write(chunk)
            total += len(chunk)

    if total <= 0:
        path.unlink(missing_ok=True)
        raise ChatMediaError("Arquivo vazio", status_code=400)

    mime = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    return {
        "id": stored_name,
        "filename": safe,
        "size": total,
        "mime": mime,
        "type": _media_type_for(ext, mime),
        "source": source,
        "url": media_public_url(stored_name),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_media_path(media_id: str) -> Path:
    safe = Path(media_id).name
    if not safe or safe != media_id:
        raise ChatMediaError("ID inválido", status_code=400)
    path = CHAT_MEDIA_DIR / safe
    if not path.is_file():
        raise ChatMediaError("Mídia não encontrada", status_code=404)
    return path


def media_item_from_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normaliza registro de mídia para resposta API / histórico."""
    mid = str(record.get("id") or "")
    filename = str(record.get("filename") or mid)
    mime = record.get("mime")
    media_type = record.get("type") or _media_type_for(Path(filename).suffix.lower(), mime)
    if media_type == "file":
        # fallback: id/url com extensão de imagem
        media_type = _media_type_for(Path(mid).suffix.lower(), mime)
    return {
        "id": mid,
        "url": record.get("url") or media_public_url(mid),
        "type": media_type,
        "filename": filename,
        "mime": mime,
        "size": record.get("size"),
    }


def _parse_tool_payload(raw: Any) -> dict[str, Any] | None:
    import json

    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_media_from_tool_results(tool_log: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tool_log or []:
        tool = str(item.get("tool") or "")
        if tool in {"windows_transfer_to_debian", "media_plan"}:
            continue
        payload = _parse_tool_payload(item.get("result") or item.get("result_preview") or "")
        if not payload:
            continue
        mid = str(payload.get("media_id") or payload.get("id") or "")
        if not mid or mid in seen:
            continue
        if payload.get("ok") is False:
            continue
        if payload.get("type") in {"transfer", "plan"}:
            continue
        seen.add(mid)
        out.append(
            media_item_from_record(
                {
                    "id": mid,
                    "url": payload.get("media_url") or payload.get("url") or media_public_url(mid),
                    "type": payload.get("media_type") or payload.get("type") or "file",
                    "filename": payload.get("filename") or mid,
                    "mime": payload.get("mime"),
                    "size": payload.get("size"),
                }
            )
        )
    return out


def extract_chat_artifacts_from_tool_log(tool_log: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Mídia rica do chat: transferências, planos de mídia, screenshots, etc."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(item: dict[str, Any]) -> None:
        mid = str(item.get("id") or "")
        if not mid or mid in seen:
            return
        seen.add(mid)
        out.append(item)

    for item in tool_log or []:
        tool = str(item.get("tool") or "")
        payload = _parse_tool_payload(item.get("result") or item.get("result_preview") or "")
        if not payload or payload.get("ok") is False:
            continue
        if tool == "windows_transfer_to_debian":
            tid = str(payload.get("id") or "")
            if tid:
                _add(
                    {
                        "id": tid,
                        "type": "transfer",
                        "filename": payload.get("filename") or "Transferência",
                        "url": f"/api/transfers/{tid}",
                    }
                )
            continue
        if tool == "media_plan":
            pid = str(payload.get("id") or payload.get("plan_id") or "")
            if pid:
                _add(
                    {
                        "id": pid,
                        "type": "plan",
                        "filename": payload.get("query") or "Plano de mídia",
                        "url": f"/api/plans/{pid}",
                    }
                )
            continue

    for media in extract_media_from_tool_results(tool_log):
        _add(media)
    return out
