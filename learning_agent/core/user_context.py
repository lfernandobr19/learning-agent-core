"""Contexto do utilizador para o motor Ravenna — fase 1 (config estática .env)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from learning_agent.config import (
    USER_ADDRESS,
    USER_CITY,
    USER_COUNTRY,
    USER_LOCALE,
    USER_REGION,
    USER_TIMEZONE,
)

# Horário regular B3 (sem after-hours) — referência para respostas temporais
_B3_OPEN_HOUR = 10
_B3_CLOSE_HOUR = 17


def is_configured() -> bool:
    return bool(USER_TIMEZONE or USER_CITY or USER_COUNTRY)


def local_now() -> datetime | None:
    if not USER_TIMEZONE:
        return None
    try:
        return datetime.now(ZoneInfo(USER_TIMEZONE))
    except ZoneInfoNotFoundError:
        return None


def profile() -> dict[str, Any]:
    now = local_now()
    return {
        "configured": is_configured(),
        "city": USER_CITY or None,
        "region": USER_REGION or None,
        "country": USER_COUNTRY or None,
        "timezone": USER_TIMEZONE or None,
        "locale": USER_LOCALE or None,
        "local_time": now.isoformat(timespec="minutes") if now else None,
        "local_time_label": now.strftime("%d/%m/%Y %H:%M") if now else None,
        "b3_session": _b3_session_label(now) if now and (USER_COUNTRY or "").upper() in {"BR", "BRA", "BRASIL"} else None,
        "address": USER_ADDRESS or None,
    }


def _b3_session_label(now: datetime) -> str:
    if now.weekday() >= 5:
        return "fechada (fim de semana)"
    hour = now.hour + now.minute / 60.0
    if hour < _B3_OPEN_HOUR:
        return "pré-abertura"
    if hour < _B3_CLOSE_HOUR:
        return "aberta"
    return "fechada (pós-pregão)"


def format_telegram_summary() -> str:
    p = profile()
    if not p["configured"]:
        return (
            "Geolocalização Ravenna não configurada.\n"
            "Defina USER_TIMEZONE e USER_CITY no .env (motor Ravenna)."
        )
    lines = ["Localização (motor Ravenna):"]
    place = ", ".join(x for x in (p["city"], p["region"], p["country"]) if x)
    if place:
        lines.append(f"• Local: {place}")
    if p["timezone"]:
        lines.append(f"• Fuso: {p['timezone']}")
    if p["local_time_label"]:
        lines.append(f"• Agora: {p['local_time_label']}")
    if p["b3_session"]:
        lines.append(f"• B3: {p['b3_session']}")
    if p["locale"]:
        lines.append(f"• Locale: {p['locale']}")
    if p.get("address"):
        lines.append(f"• Endereço (.env): {p['address']}")
    lines.append("• POIs: /casa <endereço> ou envie pin 📍, depois /perto")
    return "\n".join(lines)


def format_system_block() -> str:
    """Bloco curto para system prompt — só Ravenna (não agentes delegados)."""
    if not is_configured():
        return ""

    p = profile()
    lines = ["CONTEXTO DO UTILIZADOR (geolocalização fase 1 — .env):"]
    place = ", ".join(x for x in (p["city"], p["region"], p["country"]) if x)
    if place:
        lines.append(f"- Local: {place}")
    if p["timezone"]:
        lines.append(f"- Fuso horário: {p['timezone']}")
    if p["local_time_label"]:
        lines.append(f"- Hora local agora: {p['local_time_label']}")
    if p["locale"]:
        lines.append(f"- Locale: {p['locale']}")
    if p["b3_session"]:
        lines.append(f"- Pregão B3 (referência): {p['b3_session']}")
    lines.append(
        "Use para cumprimentos, horários e contexto regional. "
        "Não invente GPS — só estes dados estáticos."
    )
    return "\n".join(lines)


def modelfile_location_line() -> str:
    """Uma linha opcional para Modelfile (cérebro raven)."""
    if not is_configured():
        return ""
    p = profile()
    place = ", ".join(x for x in (p["city"], p["region"], p["country"]) if x)
    tz = p["timezone"] or "?"
    return f"Utilizador: {place or 'configurado'} ({tz})."
