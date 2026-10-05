"""Testes — finance_market_context (Fase A)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from learning_agent.core import finance_decision_loop as fdl
from learning_agent.core import finance_market_context as fmc


def test_format_macro_line():
    macro = {
        "indicators": {
            "selic_meta": {"value": 15.0, "date": "01/06/2026"},
            "ipca_mensal": {"value": 0.45, "date": "01/05/2026"},
        }
    }
    line = fmc.format_macro_line(macro)
    assert "Selic" in line
    assert "IPCA" in line


def test_calendar_prefer_watch_high_impact(tmp_path, monkeypatch):
    live = tmp_path / "calendar_live.json"
    live.write_text(
        json.dumps(
            {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "events": [
                    {
                        "date": "2026-06-17",
                        "title": "Copom",
                        "impact": "high",
                        "source": "test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fmc, "CALENDAR_LIVE", live)
    result = fmc.get_macro_calendar(on_date=datetime(2026, 6, 17))
    assert result["prefer_watch"] is True
    assert result["events_today"][0]["title"] == "Copom"


def test_refresh_macro_calendar_merges_sources(tmp_path, monkeypatch):
    live = tmp_path / "calendar_live.json"
    monkeypatch.setattr(fmc, "CALENDAR_LIVE", live)
    monkeypatch.setattr(fmc, "_fetch_copom_from_bcb", lambda: [])
    monkeypatch.setattr(fmc, "_fetch_copom_from_search", lambda: [])
    monkeypatch.setattr(fmc, "_load_calendar_overrides", lambda: [])
    result = fmc.refresh_macro_calendar(cache_hours=0)
    assert result.get("success")
    assert result.get("sources", {}).get("estimated_ipca", 0) >= 1
    assert live.is_file()


def test_generate_downgrades_buy_on_copom_day():
    market = fdl.load_market_context()
    enrichment = {
        "calendar": {
            "prefer_watch": True,
            "events_today": [{"title": "Copom — decisão Selic", "impact": "high"}],
        },
        "macro_line": "Macro BCB: Selic meta 15% a.a.",
        "calendar_line": "Calendário: hoje — Copom.",
        "headline": {"headline": "Selic estável", "success": True},
    }
    dec = fdl.generate_l6_decision(market, fdl.load_news_context(), enrichment=enrichment)
    if market.get("data_complete") and any(t.get("signal") == "bullish" for t in market.get("tickers", [])):
        assert dec.get("action") == "watch"
        assert dec.get("downgraded_from") == "buy"


def test_fetch_bcb_macro_cached(tmp_path, monkeypatch):
    cache = tmp_path / "bcb.json"
    monkeypatch.setattr(fmc, "BCB_CACHE", cache)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=[{"data": "01/06/2026", "valor": "15.00"}])

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return mock_resp

    monkeypatch.setattr(fmc.httpx, "Client", FakeClient)
    first = fmc.fetch_bcb_macro(cache_hours=6)
    assert first.get("success")
    second = fmc.fetch_bcb_macro(cache_hours=6)
    assert second.get("from_cache") is True
