"""Geolocalização Ravenna — geocode + POIs próximos (OpenStreetMap, sem backend extra)."""

from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from learning_agent.config import DATA_DIR, USER_ADDRESS, USER_CITY, USER_COUNTRY, USER_REGION
from learning_agent.core.web import USER_AGENT

GEO_STATE_PATH = DATA_DIR / "telegram_user_geo.json"
NOMINATIM = "https://nominatim.openstreetmap.org"
_MIN_GEO_INTERVAL_S = 1.1
_last_request_at = 0.0
# Sem update do Telegram neste intervalo → live considerada pausada (segundos)
LIVE_LOCATION_STALE_SECONDS = int(os.environ.get("LIVE_LOCATION_STALE_SECONDS", "120"))

ADDRESS_IN_TEXT_RE = re.compile(
    r"(?i)(?:moro (?:na|em|no)|moro na|cadastre (?:meu )?endere[cç]o|"
    r"meu endere[cç]o [ée]|rua\s+|av\.|avenida\s+)(.+)",
)

CURRENT_ADDRESS_RE = re.compile(
    r"(?i)"
    r"(qual (é )?(o )?)?(meu )?endere[cç]o (atual|cadastrado|salvo|configurado)"
    r"|onde (estou|eu estou|moro)"
    r"|(minha|a) localiza(ç|c)[aã]o (atual)?"
)

NEARBY_QUERY_RE = re.compile(
    r"(?i)"
    r"(mercado|supermercado|farm[aá]cia|padaria|posto|hospital|banco|atm|"
    r"restaurante|lanchonete|shopping|loja)"
    r".{0,40}(pr[oó]ximo|perto|perto de mim|mais perto|aqui|casa)"
    r"|"
    r"(pr[oó]ximo|perto|mais perto).{0,40}(mercado|supermercado|farm[aá]cia|"
    r"padaria|posto|shopping|loja)"
    r"|"
    r"qual o .{0,30}(mercado|supermercado|farm[aá]cia|padaria)"
    r"|"
    r"onde fica o .{0,30}(mercado|supermercado|farm[aá]cia)"
)

LOCATION_QUERY_RE = NEARBY_QUERY_RE  # alias retrocompatível

SHOP_ALIASES: dict[str, tuple[str, ...]] = {
    "mercado": ("supermarket", "convenience", "mall", "greengrocer"),
    "supermercado": ("supermarket", "convenience"),
    "farmacia": ("pharmacy",),
    "farmácia": ("pharmacy",),
    "padaria": ("bakery",),
    "posto": ("fuel",),
    "shopping": ("mall", "department_store"),
    "restaurante": ("restaurant", "fast_food"),
    "banco": ("bank",),
    "atm": ("atm",),
}


def _build_geocode_query(address: str) -> str:
    parts = [address.strip()]
    low = address.lower()
    if USER_CITY and USER_CITY.lower() not in low:
        parts.append(USER_CITY)
    if USER_REGION and USER_REGION.lower() not in low:
        parts.append(USER_REGION)
    country = USER_COUNTRY or "Brasil"
    if country.lower() not in low and country.upper() not in {"BR"}:
        parts.append(country if len(country) > 2 else "Brasil")
    return ", ".join(p for p in parts if p)


def _pick_best_geocode(rows: list[dict[str, Any]], original: str) -> dict[str, Any] | None:
    if not rows:
        return None
    keywords = [w.lower() for w in re.findall(r"\w{4,}", original)]
    best = rows[0]
    best_score = -1.0
    for row in rows:
        dn = (row.get("display_name") or "").lower()
        addr_blob = json.dumps(row.get("address") or {}, ensure_ascii=False).lower()
        score = float(row.get("importance") or 0)
        for kw in keywords:
            if kw in dn or kw in addr_blob:
                score += 2.0
        if USER_CITY and USER_CITY.lower() in dn:
            score += 3.0
        if USER_REGION and USER_REGION.lower() in dn:
            score += 1.5
        if score > best_score:
            best_score = score
            best = row
    return best


def _origin_label(origin: dict[str, Any]) -> str:
    label = (origin.get("address") or origin.get("display_name") or "").strip()
    if label:
        return label
    return "base configurada"


def is_live_location_active(rec: dict[str, Any], *, now: float | None = None) -> bool:
    """True se o Telegram ainda está enviando localização ao vivo."""
    if rec.get("source") != "telegram_live":
        return False
    now_ts = now if now is not None else time.time()
    live_until = rec.get("live_until_unix")
    if not live_until or now_ts >= float(live_until):
        return False
    updated = rec.get("updated_at_unix")
    if updated is None:
        return False
    return (now_ts - float(updated)) <= LIVE_LOCATION_STALE_SECONDS


def _format_age_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} s"
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    return f"{int(seconds // 3600)} h"


def location_status_line(rec: dict[str, Any], *, now: float | None = None) -> str:
    """Linha curta: ao vivo / GPS fixo / cadastro / .env."""
    now_ts = now if now is not None else time.time()
    if is_live_location_active(rec, now=now_ts):
        remaining = float(rec.get("live_until_unix", 0)) - now_ts
        return f"📡 Localização ao vivo (expira em ~{_format_age_seconds(max(0, remaining))})"
    if rec.get("source") in {"telegram_live", "telegram_gps"}:
        updated = rec.get("updated_at_unix")
        if updated:
            age = now_ts - float(updated)
            return f"📍 GPS salvo (há {_format_age_seconds(age)})"
        return "📍 GPS salvo"
    if rec.get("address"):
        return "🏠 Endereço cadastrado (/casa)"
    return "⚙️ Base do .env"


def format_current_address(user_id: str) -> str:
    rec = get_user_record(user_id)
    origin = resolve_coordinates(user_id)
    if not origin.get("success"):
        return origin.get("error", "Sem localização.")

    lines = ["Seu endereço / localização:", "", location_status_line(rec), ""]
    if rec.get("source") == "telegram_live" and origin.get("live_active"):
        lines.append(f"• Posição atual: {rec.get('display_name', rec.get('address', ''))}")
    elif rec.get("source") in {"telegram_gps", "telegram_live"}:
        lines.append(f"• GPS Telegram: {rec.get('display_name', rec.get('address', ''))}")
    elif rec.get("address"):
        lines.append(f"• Cadastro Telegram: {rec['address']}")
    elif USER_ADDRESS:
        lines.append(f"• Config (.env): {USER_ADDRESS}")

    dn = origin.get("display_name") or origin.get("address") or ""
    if dn and dn not in "\n".join(lines):
        lines.append(f"• Geocodificado: {dn}")

    lines.append(f"• Coordenadas: {float(origin['lat']):.5f}, {float(origin['lon']):.5f}")

    source = origin.get("source", "")
    if origin.get("live_active"):
        lines.extend(
            [
                "",
                "Localização ao vivo ativa — «perto de mim» usa sua posição real.",
            ]
        )
    elif source in {"env_default", "env_city"}:
        lines.extend(
            [
                "",
                "⚠️ Usando endereço do .env — pode estar impreciso se você não estiver aí.",
                "Para corrigir: /gps (GPS do celular) ou 📎 → Localização ao vivo",
            ]
        )
    elif rec.get("source") not in {"telegram_gps", "telegram_live"}:
        lines.extend(
            [
                "",
                "Dica: no Telegram, /gps ou 📎 → Localização → Compartilhar ao vivo (GPS do celular).",
            ]
        )

    return "\n".join(lines)


def is_current_address_query(text: str) -> bool:
    return bool(CURRENT_ADDRESS_RE.search(text.strip()))


def _throttle() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < _MIN_GEO_INTERVAL_S:
        time.sleep(_MIN_GEO_INTERVAL_S - elapsed)
    _last_request_at = time.monotonic()


def _load_state() -> dict[str, Any]:
    if not GEO_STATE_PATH.is_file():
        return {"users": {}}
    try:
        data = json.loads(GEO_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"users": {}}
    except json.JSONDecodeError:
        return {"users": {}}


def _save_state(data: dict[str, Any]) -> None:
    GEO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEO_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_record(user_id: str) -> dict[str, Any]:
    return (_load_state().get("users") or {}).get(str(user_id)) or {}


def set_user_address(user_id: str, address: str) -> dict[str, Any]:
    address = address.strip()
    if not address:
        return {"success": False, "error": "Endereço vazio"}
    geo = geocode_address(address)
    if not geo.get("success"):
        return geo
    data = _load_state()
    users = data.setdefault("users", {})
    users[str(user_id)] = {
        "address": address,
        "lat": geo["lat"],
        "lon": geo["lon"],
        "display_name": geo.get("display_name", address),
        "updated_at": geo.get("fetched_at"),
    }
    _save_state(data)
    return {"success": True, **users[str(user_id)]}


def resolve_coordinates(user_id: str) -> dict[str, Any]:
    rec = get_user_record(user_id)
    if rec.get("lat") is not None and rec.get("lon") is not None:
        live = is_live_location_active(rec)
        source = rec.get("source") or "telegram_saved"
        if live:
            source = "telegram_live"
        return {
            "success": True,
            "lat": float(rec["lat"]),
            "lon": float(rec["lon"]),
            "source": source,
            "live_active": live,
            "address": rec.get("address") or rec.get("display_name"),
            "display_name": rec.get("display_name") or rec.get("address"),
        }
    default = (USER_ADDRESS or "").strip()
    if default:
        geo = geocode_address(default)
        if geo.get("success"):
            return {
                **geo,
                "source": "env_default",
                "address": default,
            }
    city = ", ".join(x for x in (USER_CITY, USER_REGION, USER_COUNTRY or "Brasil") if x)
    if city:
        geo = geocode_address(city)
        if geo.get("success"):
            return {
                **geo,
                "source": "env_city",
                "address": city,
                "note": "Precisão baixa — use /casa <endereço> ou envie pin GPS",
            }
    return {
        "success": False,
        "error": "Sem GPS do celular ainda. Use /gps (botão) ou 📎 → Localização ao vivo.",
    }


def geocode_address(address: str) -> dict[str, Any]:
    _throttle()
    query = _build_geocode_query(address)
    params: dict[str, str | int] = {
        "q": query,
        "format": "json",
        "limit": 5,
        "addressdetails": 1,
    }
    if USER_COUNTRY and len(USER_COUNTRY) <= 2:
        params["countrycodes"] = USER_COUNTRY.lower()[:2]
    elif not USER_COUNTRY or USER_COUNTRY.upper() in {"BR", "BRASIL"}:
        params["countrycodes"] = "br"
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=25.0, headers=headers) as client:
            r = client.get(f"{NOMINATIM}/search?{urlencode(params)}")
            r.raise_for_status()
            rows = r.json()
    except Exception as exc:
        return {"success": False, "error": f"Geocode falhou: {exc}"}

    row = _pick_best_geocode(rows, address)
    if not row:
        return {"success": False, "error": f"Endereço não encontrado: {query[:120]}"}

    return {
        "success": True,
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "display_name": row.get("display_name", address),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _detect_shop_type(text: str) -> str:
    t = text.lower()
    for key in ("supermercado", "mercado", "farmácia", "farmacia", "padaria", "posto", "shopping", "restaurante", "banco"):
        if key in t:
            return key.replace("á", "a")
    return "supermercado"


def nearby_places(
    lat: float,
    lon: float,
    *,
    shop_type: str = "supermercado",
    radius_m: int = 2500,
    limit: int = 5,
) -> dict[str, Any]:
    shops = SHOP_ALIASES.get(shop_type, SHOP_ALIASES["supermercado"])
    shop_filter = "|".join(shops)
    query = f"""
[out:json][timeout:25];
(
  node["shop"~"^({shop_filter})$"](around:{radius_m},{lat},{lon});
  way["shop"~"^({shop_filter})$"](around:{radius_m},{lat},{lon});
);
out center {limit * 3};
"""
    _throttle()
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=30.0, headers=headers) as client:
            r = client.post(
                "https://overpass-api.de/api/interpreter",
                content=f"data={query}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return {"success": False, "error": f"Busca OSM falhou: {exc}"}

    elements = data.get("elements") or []
    places: list[dict[str, Any]] = []
    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("brand") or tags.get("operator")
        if not name:
            continue
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        dist = _haversine_km(lat, lon, float(plat), float(plon))
        street = tags.get("addr:street") or ""
        hn = tags.get("addr:housenumber") or ""
        addr = f"{street} {hn}".strip()
        places.append(
            {
                "name": name,
                "distance_km": round(dist, 2),
                "address": addr,
                "shop": tags.get("shop", ""),
                "lat": float(plat),
                "lon": float(plon),
            }
        )

    places.sort(key=lambda p: p["distance_km"])
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for p in places:
        key = p["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
        if len(unique) >= limit:
            break

    return {
        "success": bool(unique),
        "shop_type": shop_type,
        "places": unique,
        "error": None if unique else f"Nenhum {shop_type} encontrado num raio de {radius_m // 1000} km.",
    }


def is_location_query(text: str) -> bool:
    t = text.lower().strip()
    if is_current_address_query(text):
        return True
    if t.startswith(("/perto", "/casa", "/nearby", "/endereco", "/endereço")):
        return True
    if NEARBY_QUERY_RE.search(text):
        return True
    if ADDRESS_IN_TEXT_RE.search(text):
        return True
    return False


def extract_address_from_message(text: str) -> str | None:
    m = ADDRESS_IN_TEXT_RE.search(text.strip())
    if not m:
        return None
    addr = m.group(1).strip(" .,!?:;")
    if len(addr) < 8:
        return None
    if USER_CITY and USER_CITY.lower() not in addr.lower():
        addr = f"{addr}, {USER_CITY}"
    if USER_COUNTRY and USER_COUNTRY.upper() in {"BR", "BRASIL"} and "brasil" not in addr.lower():
        addr = f"{addr}, Brasil"
    return addr


def handle_location_query(text: str, user_id: str) -> str | None:
    """Resposta factual de geolocalização — None se não for pedido de local."""
    if is_current_address_query(text):
        return format_current_address(user_id)

    if not is_location_query(text):
        return None

    t = text.strip()
    if t.lower().startswith(("/endereco", "/endereço")):
        return format_current_address(user_id)

    if t.lower().startswith("/casa"):
        rest = t.split(maxsplit=1)
        addr = rest[1].strip() if len(rest) > 1 else ""
        if not addr:
            return "Uso: /casa <endereço completo>\nEx.: /casa rua dos pica-paus, 446 - Jardim Primavera"
        result = set_user_address(user_id, addr)
        if not result.get("success"):
            return f"Não gravei o endereço: {result.get('error', 'erro')}"
        return (
            f"Casa registrada.\n"
            f"📍 {result.get('display_name', addr)}\n"
            f"Lat/lon: {result.get('lat')}, {result.get('lon')}\n\n"
            "Agora pergunte: «qual supermercado mais próximo?»"
        )

    addr_inline = extract_address_from_message(text)
    if addr_inline:
        set_user_address(user_id, addr_inline)

    shop = _detect_shop_type(text)
    if t.lower().startswith(("/perto", "/nearby")):
        parts = t.split(maxsplit=1)
        if len(parts) > 1:
            shop = _detect_shop_type(parts[1])

    origin = resolve_coordinates(user_id)
    if not origin.get("success"):
        return origin.get("error", "Sem localização.")

    nearby = nearby_places(float(origin["lat"]), float(origin["lon"]), shop_type=shop)
    if not nearby.get("success"):
        return nearby.get("error", "Nada encontrado por perto.")

    origin_label = _origin_label(origin)
    live_tag = " 📡" if origin.get("live_active") else ""
    lines = [
        f"Perto de você ({origin_label}){live_tag}:",
        f"Tipo: {shop} · fonte: OpenStreetMap",
        "",
    ]
    if origin.get("live_active"):
        lines.append("Usando localização ao vivo do Telegram.")
        lines.append("")
    elif origin.get("source") in {"env_default", "env_city"}:
        lines.append("⚠️ Base do .env — use /gps ou Localização ao vivo do celular.")
        lines.append("")
    for i, p in enumerate(nearby["places"], 1):
        dist = p["distance_km"]
        dist_label = f"{int(dist * 1000)} m" if dist < 1 else f"{dist:.1f} km"
        line = f"{i}. {p['name']} — {dist_label}"
        if p.get("address"):
            line += f"\n   {p['address']}"
        lines.append(line)
    lines.append("")
    lines.append("Mapa: https://www.openstreetmap.org/search?query=" + shop.replace(" ", "+"))
    return "\n".join(lines)


def save_telegram_location(
    user_id: str,
    lat: float,
    lon: float,
    *,
    live_period: int | None = None,
    message_date: int | None = None,
    horizontal_accuracy: float | None = None,
    silent_update: bool = False,
) -> dict[str, Any]:
    """Grava pin GPS ou atualização de localização ao vivo (Telegram)."""
    existing = get_user_record(user_id)
    now = time.time()
    msg_ts = float(message_date) if message_date else now

    skip_reverse = False
    if silent_update and existing.get("lat") is not None and existing.get("lon") is not None:
        moved = _haversine_km(float(existing["lat"]), float(existing["lon"]), lat, lon)
        skip_reverse = moved < 0.15

    if skip_reverse:
        display = existing.get("display_name") or existing.get("address") or f"GPS {lat:.5f}, {lon:.5f}"
        err = None
    else:
        _throttle()
        headers = {"User-Agent": USER_AGENT}
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                r = client.get(
                    f"{NOMINATIM}/reverse?{urlencode({'lat': lat, 'lon': lon, 'format': 'json'})}"
                )
                r.raise_for_status()
                row = r.json()
        except Exception as exc:
            row = {}
            display = existing.get("display_name") or f"GPS {lat:.5f}, {lon:.5f}"
            err = str(exc)
        else:
            display = row.get("display_name", f"GPS {lat:.5f}, {lon:.5f}")
            err = None

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rec: dict[str, Any] = {
        "address": display,
        "lat": lat,
        "lon": lon,
        "display_name": display,
        "updated_at": now_iso,
        "updated_at_unix": now,
    }
    if horizontal_accuracy is not None:
        rec["horizontal_accuracy_m"] = horizontal_accuracy

    if live_period and live_period > 0:
        rec["source"] = "telegram_live"
        rec["live_period"] = int(live_period)
        if not existing.get("live_started_at_unix") or not silent_update:
            rec["live_started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(msg_ts))
            rec["live_started_at_unix"] = msg_ts
        else:
            rec["live_started_at"] = existing.get("live_started_at")
            rec["live_started_at_unix"] = existing.get("live_started_at_unix")
        rec["live_until_unix"] = msg_ts + int(live_period)
    else:
        rec["source"] = "telegram_gps"

    data = _load_state()
    users = data.setdefault("users", {})
    users[str(user_id)] = rec
    _save_state(data)

    live_active = is_live_location_active(rec)
    out: dict[str, Any] = {
        "success": True,
        "display_name": display,
        "lat": lat,
        "lon": lon,
        "live_active": live_active,
        "live_period": rec.get("live_period"),
        "silent_update": silent_update,
    }
    if err:
        out["warning"] = err
    return out
