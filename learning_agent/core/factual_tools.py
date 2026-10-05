"""Ferramentas factuais Ravenna — clima, câmbio, router web automático."""

from __future__ import annotations

import re
from typing import Any

import httpx

from learning_agent.core.web import USER_AGENT, format_web_search_telegram

# Router automático → busca web (sem precisar dizer /web)
AUTO_WEB_RE = re.compile(
    r"(?i)"
    r"(cotação|cotaçao|cotacao|quanto (est[aá]|t[aá])|valor (do|da|de))"
    r".{0,30}(d[oó]lar|usd|euro|eur|bitcoin|btc|ibovespa|selic|ipca)"
    r"|"
    r"(not[ií]cia|noticia)s?.{0,20}(hoje|agora|últim|ultim)"
    r"|"
    r"(hoje|agora).{0,25}(not[ií]cia|mercado|economia|d[oó]lar|cotação)"
    r"|"
    r"o que (aconteceu|rolou).{0,20}(hoje|mercado)"
)

WEATHER_RE = re.compile(
    r"(?i)(clima|tempo|temperatura|vai chover|previsão|previsao).{0,30}(hoje|amanh[aã]|agora)?"
)

FX_RE = re.compile(
    r"(?i)"
    r"(cotação|cotaçao|cotacao|quanto (est[aá]|t[aá])|valor)"
    r".{0,25}(d[oó]lar|usd.?brl|real.?d[oó]lar|eur|euro)"
    r"|"
    r"d[oó]lar (hoje|agora|comercial)"
)


def is_auto_web_query(text: str) -> bool:
    t = text.strip()
    if t.startswith("/web"):
        return False
    if WEATHER_RE.search(t) or FX_RE.search(t):
        return False
    return bool(AUTO_WEB_RE.search(t))


def build_auto_web_query(text: str) -> str:
    t = text.strip()
    if "dólar" in t.lower() or "dolar" in t.lower():
        return "cotação dólar comercial hoje Brasil"
    if "ibovespa" in t.lower():
        return "Ibovespa hoje fechamento"
    if "selic" in t.lower():
        return "taxa Selic meta hoje Brasil"
    if "notícia" in t.lower() or "noticia" in t.lower():
        return f"notícias economia Brasil hoje {t[:80]}"
    return t[:120]


def fetch_weather(lat: float, lon: float, *, city_label: str = "") -> dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "precipitation,weather_code,wind_speed_10m"
        "&timezone=auto"
    )
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    cur = data.get("current") or {}
    code = int(cur.get("weather_code") or 0)
    desc = _wmo_label(code)
    return {
        "success": True,
        "city": city_label,
        "temperature_c": cur.get("temperature_2m"),
        "feels_like_c": cur.get("apparent_temperature"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "wind_kmh": cur.get("wind_speed_10m"),
        "description": desc,
    }


def _wmo_label(code: int) -> str:
    mapping = {
        0: "céu limpo",
        1: "principalmente limpo",
        2: "parcialmente nublado",
        3: "nublado",
        45: "neblina",
        48: "neblina com geada",
        51: "garoa leve",
        53: "garoa moderada",
        55: "garoa forte",
        61: "chuva leve",
        63: "chuva moderada",
        65: "chuva forte",
        80: "pancadas de chuva",
        95: "tempestade",
    }
    return mapping.get(code, f"condição {code}")


def format_weather_telegram(lat: float, lon: float, *, city_label: str = "") -> str:
    w = fetch_weather(lat, lon, city_label=city_label)
    if not w.get("success"):
        return f"Clima indisponível: {w.get('error', 'erro')}"
    place = city_label or f"{lat:.4f}, {lon:.4f}"
    lines = [
        f"Clima agora — {place}",
        f"• {w['description'].capitalize()}",
        f"• Temperatura: {w['temperature_c']}°C (sensação {w['feels_like_c']}°C)",
        f"• Umidade: {w['humidity_pct']}% · vento {w['wind_kmh']} km/h",
    ]
    if w.get("precipitation_mm"):
        lines.append(f"• Chuva: {w['precipitation_mm']} mm")
    lines.append("— Open-Meteo")
    return "\n".join(lines)


def fetch_fx_rates() -> dict[str, Any]:
    """USD/BRL e EUR/BRL via AwesomeAPI (público, sem chave)."""
    url = "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL"
    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    out: dict[str, Any] = {"success": True, "pairs": {}}
    for key, label in (("USDBRL", "USD/BRL"), ("EURBRL", "EUR/BRL")):
        row = data.get(key)
        if not isinstance(row, dict):
            continue
        bid = row.get("bid") or row.get("ask")
        if bid:
            out["pairs"][label] = {
                "bid": float(bid),
                "timestamp": row.get("create_date") or row.get("timestamp"),
            }
    if not out["pairs"]:
        return {"success": False, "error": "Paridade não retornada"}
    return out


def format_fx_telegram() -> str:
    fx = fetch_fx_rates()
    if not fx.get("success"):
        # fallback yfinance
        try:
            import yfinance as yf

            usd = yf.Ticker("USDBRL=X").fast_info.get("last_price")
            eur = yf.Ticker("EURBRL=X").fast_info.get("last_price")
            lines = ["Câmbio (yfinance):", ""]
            if usd:
                lines.append(f"• USD/BRL: R$ {float(usd):.4f}")
            if eur:
                lines.append(f"• EUR/BRL: R$ {float(eur):.4f}")
            lines.append("— ao vivo")
            return "\n".join(lines)
        except Exception as exc2:
            return f"Câmbio indisponível: {fx.get('error')} / {exc2}"

    lines = ["Câmbio agora:", ""]
    for pair, row in fx["pairs"].items():
        lines.append(f"• {pair}: R$ {row['bid']:.4f}")
        if row.get("timestamp"):
            lines.append(f"  ({row['timestamp']})")
    lines.append("— AwesomeAPI")
    return "\n".join(lines)


def is_weather_query(text: str) -> bool:
    return bool(WEATHER_RE.search(text))


def is_fx_query(text: str) -> bool:
    return bool(FX_RE.search(text))


def handle_factual_query(text: str, user_id: str) -> str | None:
    """Ferramentas factuais — None se não aplicável."""
    from learning_agent.core import user_geolocation as ug

    if is_fx_query(text):
        return format_fx_telegram()

    if is_weather_query(text):
        origin = ug.resolve_coordinates(user_id)
        if not origin.get("success"):
            return origin.get("error", "Sem localização para clima. Use /casa ou pin 📍.")
        label = origin.get("display_name") or origin.get("address") or "sua base"
        return format_weather_telegram(
            float(origin["lat"]),
            float(origin["lon"]),
            city_label=str(label)[:80],
        )

    if is_auto_web_query(text):
        q = build_auto_web_query(text)
        return format_web_search_telegram(q, limit=4) + "\n\n— busca automática (notícias/cotação)"

    return None
