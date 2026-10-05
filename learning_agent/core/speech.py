"""Transcrição de áudio — Telegram voice → texto (Groq Whisper ou OpenAI-compatible)."""

from __future__ import annotations

from typing import Any

import httpx

from learning_agent.config import (
    SPEECH_API_BASE,
    SPEECH_API_KEY,
    SPEECH_ENABLED,
    SPEECH_MODEL,
    TELEGRAM_BOT_TOKEN,
)


def is_configured() -> bool:
    return SPEECH_ENABLED and bool(SPEECH_API_KEY) and bool(TELEGRAM_BOT_TOKEN)


def configuration_hint() -> str:
    if not SPEECH_ENABLED:
        return "SPEECH_ENABLED=false no .env"
    if not SPEECH_API_KEY:
        return "Defina SPEECH_API_KEY (ou use TEACHER_API_KEY / Groq)."
    return ""


def download_telegram_file(file_id: str) -> bytes:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN não configurado")
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    with httpx.Client(timeout=60.0) as client:
        meta = client.get(f"{base}/getFile", params={"file_id": file_id}).json()
        if not meta.get("ok"):
            raise RuntimeError(meta.get("description", "getFile falhou"))
        path = meta["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}"
        data = client.get(url).content
    if not data:
        raise RuntimeError("Arquivo de áudio vazio")
    return data


def transcribe_audio(
    audio: bytes,
    *,
    filename: str = "voice.ogg",
    language: str = "pt",
) -> dict[str, Any]:
    """Transcreve OGG/Opus (Telegram) ou outros formatos suportados pelo Whisper."""
    if not is_configured():
        return {"success": False, "error": configuration_hint() or "Speech não configurado"}

    url = f"{SPEECH_API_BASE.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {SPEECH_API_KEY}"}
    files = {"file": (filename, audio, "audio/ogg")}
    data = {"model": SPEECH_MODEL, "language": language, "response_format": "json"}

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"success": False, "error": f"Transcrição falhou: {exc}"}

    text = (payload.get("text") or "").strip()
    if not text:
        return {"success": False, "error": "Áudio sem fala detectada."}
    return {"success": True, "text": text, "model": SPEECH_MODEL}


def transcribe_telegram_voice(file_id: str) -> dict[str, Any]:
    try:
        raw = download_telegram_file(file_id)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return transcribe_audio(raw)
