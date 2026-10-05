"""Contexto de mercado Fase A — refresh yfinance, macro BCB, calendário."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from learning_agent.config import PROJECT_ROOT

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
CALENDAR_CFG = FINANCE_ROOT / "config" / "macro_calendar.yaml"
CALENDAR_LIVE = FINANCE_ROOT / "data" / "macro_calendar_live.json"
BCB_CACHE = FINANCE_ROOT / "data" / "bcb_macro_cache.json"
DIV_MANIFEST = FINANCE_ROOT / "data" / "diversified_manifest.json"
BCB_CRONOGRAMA_URL = "https://www.bcb.gov.br/controleinflacao/cronograma"

_MONTHS_PT = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)

# Séries SGS BCB (públicas)
BCB_SERIES = {
    "selic_meta": 11,  # Meta Selic % a.a.
    "ipca_mensal": 433,  # IPCA variação mensal %
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_age_hours() -> float | None:
    if not DIV_MANIFEST.is_file():
        return None
    try:
        mtime = DIV_MANIFEST.stat().st_mtime
        return (_utcnow().timestamp() - mtime) / 3600
    except OSError:
        return None


def refresh_market_for_decision(*, force: bool = False) -> dict[str, Any]:
    """Atualiza diversified_manifest via yfinance (se stale ou force)."""
    max_age = float(os.environ.get("FINANCE_MARKET_MAX_AGE_HOURS", "6"))
    age = _manifest_age_hours()
    if not force and age is not None and age < max_age:
        return {
            "success": True,
            "skipped": True,
            "reason": f"manifest fresh ({age:.1f}h < {max_age}h)",
            "age_hours": age,
        }
    from learning_agent.core import finance_training_extensions

    result = finance_training_extensions.run_diversified_data_fetch(source="auto")
    return {
        "success": bool(result.get("success")),
        "skipped": False,
        "sources": (result.get("summary") or {}).get("data_sources"),
        "tickers_ok": (result.get("summary") or {}).get("ok"),
        "detail": result,
    }


def fetch_bcb_macro(*, cache_hours: float = 6) -> dict[str, Any]:
    """Selic meta + IPCA mensal via API BCB."""
    cached = _read_json(BCB_CACHE, {})
    if cached.get("fetched_at"):
        try:
            fetched = datetime.fromisoformat(cached["fetched_at"])
            if (_utcnow() - fetched).total_seconds() < cache_hours * 3600:
                return {**cached, "from_cache": True}
        except ValueError:
            pass

    indicators: dict[str, Any] = {}
    errors: list[str] = []
    for name, code in BCB_SERIES.items():
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/1?formato=json"
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                rows = resp.json()
            if rows and isinstance(rows, list):
                row = rows[0]
                indicators[name] = {
                    "value": float(row.get("valor", 0)),
                    "date": row.get("data"),
                    "series": code,
                }
        except Exception as exc:
            errors.append(f"{name}: {exc!r}")

    payload = {
        "success": bool(indicators),
        "indicators": indicators,
        "fetched_at": _utcnow().isoformat(timespec="seconds"),
        "errors": errors,
        "from_cache": False,
    }
    if indicators:
        _write_json(BCB_CACHE, payload)
    elif cached.get("indicators"):
        return {**cached, "from_cache": True, "stale": True}
    return payload


def _normalize_event(date_str: str, title: str, impact: str, source: str) -> dict[str, Any]:
    return {
        "date": date_str,
        "title": title,
        "impact": impact,
        "source": source,
    }


def _next_weekday(year: int, month: int, day: int) -> datetime:
    """Ajusta para dia útil se cair em fim de semana."""
    dt = datetime(year, month, day)
    while dt.weekday() >= 5:
        dt += timedelta(days=1)
    return dt


def _estimate_ipca_releases(*, months_ahead: int = 8) -> list[dict[str, Any]]:
    """Estimativa IBGE — IPCA costuma sair ~10º dia útil do mês."""
    events: list[dict[str, Any]] = []
    start = datetime.now().replace(day=1)
    for offset in range(months_ahead):
        month_base = (start.replace(day=1) + timedelta(days=32 * offset)).replace(day=1)
        release = _next_weekday(month_base.year, month_base.month, 10)
        if release.date() < datetime.now().date():
            continue
        ref_month = month_base - timedelta(days=1)
        ref_name = _MONTHS_PT[ref_month.month - 1]
        events.append(
            _normalize_event(
                release.strftime("%Y-%m-%d"),
                f"IPCA — divulgação IBGE (ref. {ref_name})",
                "medium",
                "estimated_ipca",
            )
        )
    return events


def _parse_copom_from_text(text: str, *, source: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    lower = text.lower()
    for match in re.finditer(r"(\d{2})/(\d{2})/(\d{4})", text):
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if y < datetime.now().year:
            continue
        start = max(0, match.start() - 120)
        ctx = lower[start : match.end() + 120]
        if not any(k in ctx for k in ("copom", "política monet", "politica monet", "reunião", "reuniao")):
            continue
        iso = f"{y:04d}-{m:02d}-{d:02d}"
        if iso in seen:
            continue
        seen.add(iso)
        events.append(
            _normalize_event(iso, "Copom — decisão Selic", "high", source)
        )
    return events


def _fetch_copom_from_bcb() -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            resp = client.get(
                BCB_CRONOGRAMA_URL,
                headers={"User-Agent": "finance-lead/1.0 (macro calendar)"},
            )
            resp.raise_for_status()
            return _parse_copom_from_text(resp.text, source="bcb_html")
    except Exception:
        return []


def _fetch_copom_from_search() -> list[dict[str, Any]]:
    try:
        from learning_agent.core import web

        hits = web.search_web("cronograma Copom 2026 datas reunião BCB", limit=5)
    except Exception:
        return []
    blob = " ".join(
        f"{h.get('title', '')} {h.get('body', '')} {h.get('href', '')}" for h in hits
    )
    return _parse_copom_from_text(blob, source="web_search")


def _load_calendar_overrides() -> list[dict[str, Any]]:
    if not CALENDAR_CFG.is_file():
        return []
    cfg = yaml.safe_load(CALENDAR_CFG.read_text(encoding="utf-8")) or {}
    overrides = cfg.get("overrides") or cfg.get("events") or []
    out: list[dict[str, Any]] = []
    for ev in overrides:
        if not ev.get("date"):
            continue
        out.append(
            _normalize_event(
                str(ev["date"]),
                str(ev.get("title", "Evento macro")),
                str(ev.get("impact", "medium")).lower(),
                "manual_override",
            )
        )
    return out


def refresh_macro_calendar(*, cache_hours: float | None = None) -> dict[str, Any]:
    """Sincroniza calendário macro (Copom + IPCA estimado) — sem edição manual."""
    if cache_hours is None:
        cache_hours = float(os.environ.get("FINANCE_CALENDAR_CACHE_HOURS", "24"))
    cached = _read_json(CALENDAR_LIVE, {})
    if cached.get("synced_at"):
        try:
            synced = datetime.fromisoformat(cached["synced_at"])
            if (_utcnow() - synced).total_seconds() < cache_hours * 3600:
                return {**cached, "from_cache": True}
        except ValueError:
            pass

    sources: dict[str, int] = {}
    merged: dict[str, dict[str, Any]] = {}

    for ev in _estimate_ipca_releases():
        merged[ev["date"] + ev["title"]] = ev
        sources["estimated_ipca"] = sources.get("estimated_ipca", 0) + 1

    for ev in _fetch_copom_from_bcb():
        merged[ev["date"] + ev["title"]] = ev
        sources["bcb_html"] = sources.get("bcb_html", 0) + 1

    if sources.get("bcb_html", 0) == 0:
        for ev in _fetch_copom_from_search():
            merged[ev["date"] + ev["title"]] = ev
            sources["web_search"] = sources.get("web_search", 0) + 1

    for ev in _load_calendar_overrides():
        merged[ev["date"] + ev["title"]] = ev
        sources["manual_override"] = sources.get("manual_override", 0) + 1

    events = sorted(merged.values(), key=lambda e: e["date"])
    payload = {
        "success": bool(events),
        "synced_at": _utcnow().isoformat(timespec="seconds"),
        "events": events,
        "sources": sources,
        "from_cache": False,
    }
    _write_json(CALENDAR_LIVE, payload)
    return payload


def _calendar_events(*, on_date: datetime | None = None) -> tuple[list[dict], list[dict], bool]:
    live = _read_json(CALENDAR_LIVE, {})
    events = live.get("events") or []
    if not events:
        refresh_macro_calendar()
        events = (_read_json(CALENDAR_LIVE, {}) or {}).get("events") or []

    when = on_date or datetime.now()
    today = when.strftime("%Y-%m-%d")
    tomorrow = (when + timedelta(days=1)).strftime("%Y-%m-%d")
    events_today: list[dict[str, Any]] = []
    events_soon: list[dict[str, Any]] = []
    prefer_watch = False

    for ev in events:
        d = str(ev.get("date", ""))
        impact = str(ev.get("impact", "medium")).lower()
        item = {
            "date": d,
            "title": ev.get("title", ""),
            "impact": impact,
            "source": ev.get("source", ""),
        }
        if d == today:
            events_today.append(item)
            if impact == "high":
                prefer_watch = True
        elif d == tomorrow and impact == "high":
            events_soon.append(item)

    return events_today, events_soon, prefer_watch


def get_macro_calendar(*, on_date: datetime | None = None) -> dict[str, Any]:
    """Eventos macro na data — calendário auto-sincronizado."""
    when = on_date or datetime.now()
    today = when.strftime("%Y-%m-%d")
    events_today, events_soon, prefer_watch = _calendar_events(on_date=when)
    return {
        "success": True,
        "date": today,
        "events_today": events_today,
        "events_soon": events_soon,
        "prefer_watch": prefer_watch,
        "auto": True,
    }


def pick_headline(*, limit: int = 1) -> dict[str, Any]:
    """Headline recente do manifest de notícias."""
    manifest_path = FINANCE_ROOT / "data" / "economic_news_manifest.json"
    manifest = _read_json(manifest_path, {})
    items = manifest.get("items") or []
    if not items:
        from learning_agent.core import finance_economic_news

        try:
            finance_economic_news.fetch_and_index_economic_news(use_web_fallback=False)
            manifest = _read_json(manifest_path, {})
            items = manifest.get("items") or []
        except Exception:
            pass
    if not items:
        return {"success": False, "headline": ""}
    top = items[0]
    return {
        "success": True,
        "headline": str(top.get("title", ""))[:160],
        "source": top.get("source", ""),
    }


def format_macro_line(macro: dict[str, Any]) -> str:
    ind = macro.get("indicators") or {}
    parts: list[str] = []
    selic = ind.get("selic_meta")
    ipca = ind.get("ipca_mensal")
    if selic:
        parts.append(f"Selic meta {selic['value']}% a.a. ({selic.get('date', '')})")
    if ipca:
        parts.append(f"IPCA {ipca['value']}% no mês ({ipca.get('date', '')})")
    if not parts:
        return ""
    return "Macro BCB: " + "; ".join(parts) + "."


def format_calendar_line(calendar: dict[str, Any]) -> str:
    today = calendar.get("events_today") or []
    if not today:
        soon = calendar.get("events_soon") or []
        if soon:
            s = soon[0]
            return f"Calendário: amanhã — {s.get('title')} (cautela)."
        return ""
    titles = ", ".join(e.get("title", "") for e in today[:2])
    if calendar.get("prefer_watch"):
        return f"Calendário: hoje — {titles}. Evento de alto impacto → preferir observar."
    return f"Calendário: hoje — {titles}."


def prepare_decision_context(*, refresh: bool = True, force_market: bool = False) -> dict[str, Any]:
    """Pacote Fase A antes de generate_l6_decision."""
    force_live = force_market or os.environ.get("FINANCE_DECISION_FORCE_LIVE", "1").lower() in {
        "1",
        "true",
        "yes",
    }
    refresh_result = (
        refresh_market_for_decision(force=force_live) if refresh else {"skipped": True}
    )
    macro = fetch_bcb_macro()
    calendar_sync = refresh_macro_calendar()
    calendar = get_macro_calendar()
    headline = pick_headline()
    return {
        "refresh": refresh_result,
        "macro": macro,
        "calendar": calendar,
        "calendar_sync": calendar_sync,
        "headline": headline,
        "macro_line": format_macro_line(macro),
        "calendar_line": format_calendar_line(calendar),
    }
