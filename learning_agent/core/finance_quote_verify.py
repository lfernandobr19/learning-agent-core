"""Verificação de cotações — freshness e divergência entre fontes (autonomia)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

FINANCE_ROOT_ENV = "FINANCE_QUOTE_MAX_DIVERGENCE_PCT"
DEFAULT_MAX_DIVERGENCE = 3.0
DEFAULT_MAX_AGE_HOURS = 24.0


def _yfinance_symbol(ticker: str) -> str:
    t = ticker.upper().strip()
    if t.endswith(".SA"):
        return t
    if re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return f"{t}.SA"
    return t


def fetch_live_close(ticker: str) -> dict[str, Any]:
    """Último close via yfinance (fonte independente do manifest)."""
    try:
        import yfinance as yf
    except ImportError:
        return {"success": False, "error": "yfinance não instalado"}

    symbol = _yfinance_symbol(ticker)
    try:
        hist = yf.Ticker(symbol).history(period="5d")
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}
    if hist is None or hist.empty:
        return {"success": False, "error": f"sem histórico para {symbol}"}

    last = hist.iloc[-1]
    ts = hist.index[-1]
    age_hours = (datetime.now(timezone.utc) - ts.to_pydatetime().replace(tzinfo=timezone.utc)).total_seconds() / 3600
    return {
        "success": True,
        "source": "yfinance",
        "symbol": symbol,
        "close": float(last["Close"]),
        "as_of": ts.isoformat(),
        "age_hours": round(max(0.0, age_hours), 2),
    }


def verify_quote(
    ticker: str,
    reference_price: float,
    *,
    data_source: str = "mixed",
    manifest_age_hours: float | None = None,
) -> dict[str, Any]:
    """Compara preço de referência com yfinance; falha se stale ou divergente."""
    max_div = float(os.environ.get(FINANCE_ROOT_ENV, str(DEFAULT_MAX_DIVERGENCE)))
    max_age = float(os.environ.get("FINANCE_QUOTE_MAX_AGE_HOURS", str(DEFAULT_MAX_AGE_HOURS)))

    if reference_price <= 0:
        return {"passed": False, "detail": "preço de referência inválido"}

    src = (data_source or "").lower()
    if src == "fixture":
        if manifest_age_hours is not None and manifest_age_hours > max_age:
            return {
                "passed": False,
                "detail": f"fixture stale ({manifest_age_hours:.1f}h > {max_age}h)",
            }
        return {"passed": True, "detail": "fixture — freshness OK (sem cross-check live)"}

    live = fetch_live_close(ticker)
    if not live.get("success"):
        return {
            "passed": False,
            "detail": f"live indisponível: {live.get('error', '?')}",
            "live": live,
        }

    age = float(live.get("age_hours") or 999)
    if age > max_age:
        return {
            "passed": False,
            "detail": f"cotação stale ({age:.1f}h > {max_age}h)",
            "live": live,
        }

    live_price = float(live["close"])
    div_pct = abs(live_price - reference_price) / reference_price * 100
    if div_pct > max_div:
        return {
            "passed": False,
            "detail": (
                f"divergência {div_pct:.2f}% (ref={reference_price:.2f} live={live_price:.2f} max={max_div}%)"
            ),
            "live": live,
            "divergence_pct": round(div_pct, 3),
        }

    return {
        "passed": True,
        "detail": f"OK ref={reference_price:.2f} live={live_price:.2f} div={div_pct:.2f}%",
        "live": live,
        "divergence_pct": round(div_pct, 3),
    }


def verify_market_tickers(market: dict[str, Any]) -> dict[str, Any]:
    """Verifica todos os tickers do manifest de mercado."""
    from learning_agent.core import finance_market_context

    age = finance_market_context._manifest_age_hours()
    failures: list[str] = []
    checked = 0
    for t in market.get("tickers") or []:
        ticker = str(t.get("ticker") or "")
        price = float(t.get("last_close") or 0)
        if not ticker or price <= 0:
            continue
        checked += 1
        r = verify_quote(
            ticker,
            price,
            data_source=str(t.get("data_source") or "mixed"),
            manifest_age_hours=age,
        )
        if not r.get("passed"):
            failures.append(f"{ticker}: {r.get('detail')}")

    if checked == 0:
        return {"passed": False, "detail": "nenhum ticker com preço no manifest"}
    if failures:
        return {
            "passed": False,
            "detail": "; ".join(failures[:3]),
            "checked": checked,
            "failures": failures,
        }
    return {"passed": True, "detail": f"{checked} tickers OK", "checked": checked}
