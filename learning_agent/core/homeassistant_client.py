"""Cliente sync Home Assistant para tools do motor Ravenna."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

HA_URL = (os.environ.get("HOME_ASSISTANT_URL") or "").rstrip("/")
HA_TOKEN = os.environ.get("HOME_ASSISTANT_TOKEN") or ""

DEFAULT_LIGHT = (os.environ.get("HOME_ASSISTANT_DEFAULT_LIGHT") or "light.meu_quarto").strip()

COLOR_NAMES: dict[str, list[int]] = {
    "vermelho": [255, 0, 0],
    "vermelha": [255, 0, 0],
    "red": [255, 0, 0],
    "verde": [0, 220, 40],
    "green": [0, 220, 40],
    "azul": [30, 80, 255],
    "blue": [30, 80, 255],
    "branco": [255, 255, 255],
    "branca": [255, 255, 255],
    "white": [255, 255, 255],
    "amarelo": [255, 220, 40],
    "amarela": [255, 220, 40],
    "yellow": [255, 220, 40],
    "laranja": [255, 140, 0],
    "orange": [255, 140, 0],
    "rosa": [255, 80, 160],
    "pink": [255, 80, 160],
    "roxo": [140, 40, 255],
    "roxa": [140, 40, 255],
    "purple": [140, 40, 255],
    "violeta": [140, 40, 255],
    "ciano": [0, 220, 255],
    "cyan": [0, 220, 255],
    "turquesa": [0, 200, 180],
    "magenta": [255, 0, 200],
    "quente": [255, 180, 90],
    "frio": [180, 210, 255],
}


def configured() -> bool:
    return bool(HA_URL and HA_TOKEN)


def resolve_color_name(name: str | None) -> list[int] | None:
    if not name:
        return None
    key = re.sub(r"\s+", " ", name.strip().lower())
    if key in COLOR_NAMES:
        return list(COLOR_NAMES[key])
    for part in reversed(key.split()):
        if part in COLOR_NAMES:
            return list(COLOR_NAMES[part])
    return None


def _request(method: str, path: str, body: dict[str, Any] | None = None, *, timeout: float = 15.0) -> Any:
    if not configured():
        return {"ok": False, "error": "HOME_ASSISTANT_URL/TOKEN não configurados"}
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{HA_URL}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        return {"ok": False, "error": f"HTTP {exc.code}", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def list_lights(*, limit: int = 40) -> dict[str, Any]:
    states = _request("GET", "/api/states")
    if isinstance(states, dict) and states.get("ok") is False:
        return states
    if not isinstance(states, list):
        return {"ok": False, "error": "resposta inválida", "lights": []}
    lights = [s for s in states if str(s.get("entity_id", "")).startswith("light.")]
    rows = []
    for s in lights[:limit]:
        attrs = s.get("attributes") or {}
        rows.append(
            {
                "entity_id": s.get("entity_id"),
                "state": s.get("state"),
                "friendly_name": attrs.get("friendly_name"),
                "brightness": attrs.get("brightness"),
                "rgb_color": attrs.get("rgb_color"),
                "hs_color": attrs.get("hs_color"),
                "color_temp_kelvin": attrs.get("color_temp_kelvin"),
            }
        )
    return {"ok": True, "configured": True, "default_light": DEFAULT_LIGHT, "lights": rows}


def set_light(
    *,
    entity_id: str | None = None,
    action: str = "on",
    brightness_pct: int | None = None,
    color_name: str | None = None,
    rgb_color: list[int] | None = None,
    hs_color: list[float] | None = None,
    color_temp_kelvin: int | None = None,
) -> dict[str, Any]:
    eid = (entity_id or DEFAULT_LIGHT).strip() or DEFAULT_LIGHT
    act = (action or "on").strip().lower()
    if act in {"off", "desligar", "apagar"}:
        result = _request("POST", "/api/services/light/turn_off", {"entity_id": eid})
        if isinstance(result, dict) and result.get("ok") is False:
            return result
        return {"ok": True, "entity_id": eid, "service": "light.turn_off"}

    if act in {"toggle", "alternar"}:
        result = _request("POST", "/api/services/light/toggle", {"entity_id": eid})
        if isinstance(result, dict) and result.get("ok") is False:
            return result
        return {"ok": True, "entity_id": eid, "service": "light.toggle"}

    payload: dict[str, Any] = {"entity_id": eid}
    if brightness_pct is not None:
        payload["brightness_pct"] = max(0, min(100, int(brightness_pct)))

    rgb = None
    if rgb_color and len(rgb_color) >= 3:
        rgb = [max(0, min(255, int(rgb_color[0]))), max(0, min(255, int(rgb_color[1]))), max(0, min(255, int(rgb_color[2])))]
    if rgb is None:
        rgb = resolve_color_name(color_name)
    if rgb is not None:
        payload["rgb_color"] = rgb
    elif hs_color and len(hs_color) >= 2:
        payload["hs_color"] = [float(hs_color[0]) % 360, max(0.0, min(100.0, float(hs_color[1])))]
    elif color_temp_kelvin is not None:
        payload["color_temp_kelvin"] = max(2000, min(6500, int(color_temp_kelvin)))

    result = _request("POST", "/api/services/light/turn_on", payload)
    if isinstance(result, dict) and result.get("ok") is False:
        return result
    return {
        "ok": True,
        "entity_id": eid,
        "service": "light.turn_on",
        "rgb_color": payload.get("rgb_color"),
        "brightness_pct": payload.get("brightness_pct"),
        "color_temp_kelvin": payload.get("color_temp_kelvin"),
    }
