"""Performance paper + elegibilidade graduação paper → live."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
JOURNAL_PATH = FINANCE_ROOT / "data" / "paper_journal.json"
PORTFOLIO_PATH = FINANCE_ROOT / "data" / "paper_portfolio.json"
PERF_PATH = FINANCE_ROOT / "data" / "paper_performance.json"


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


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _trade_pnl(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PnL simples por par buy/sell (FIFO por ticker)."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for t in trades:
        tk = str(t.get("ticker") or "").upper()
        by_ticker.setdefault(tk, []).append(t)

    closed: list[dict[str, Any]] = []
    for ticker, seq in by_ticker.items():
        buys: list[dict[str, Any]] = []
        for t in seq:
            side = str(t.get("side") or "").lower()
            qty = int(t.get("qty") or 0)
            price = float(t.get("price") or 0)
            slip = float(t.get("slippage_pct") or 0) / 100
            if side == "buy":
                buys.append({"qty": qty, "price": price * (1 + slip)})
            elif side == "sell" and buys:
                b = buys.pop(0)
                match_qty = min(qty, b["qty"])
                pnl = (price * (1 - slip) - b["price"]) * match_qty
                closed.append({"ticker": ticker, "pnl_brl": round(pnl, 2), "qty": match_qty})
    return closed


def compute_paper_performance(*, days: int | None = None) -> dict[str, Any]:
    window = days or int(os.environ.get("FINANCE_PERF_WINDOW_DAYS", "90"))
    journal = _read_json(JOURNAL_PATH, {"trades": []})
    trades = journal.get("trades") or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=window)

    recent = []
    for t in trades:
        ts = _parse_ts(str(t.get("executed_at") or t.get("at") or ""))
        if ts is None or ts >= cutoff:
            recent.append(t)

    closed = _trade_pnl(recent)
    total_pnl = sum(c["pnl_brl"] for c in closed)
    wins = sum(1 for c in closed if c["pnl_brl"] > 0)
    losses = sum(1 for c in closed if c["pnl_brl"] < 0)
    win_rate = (wins / len(closed) * 100) if closed else 0.0

    portfolio = _read_json(PORTFOLIO_PATH, {"cash_brl": 100_000.0, "positions": []})
    from learning_agent.core import finance_risk_engine

    dd = finance_risk_engine.estimate_drawdown_pct(portfolio)

    report = {
        "success": True,
        "window_days": window,
        "trades_total": len(trades),
        "trades_in_window": len(recent),
        "closed_round_trips": len(closed),
        "pnl_brl": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "wins": wins,
        "losses": losses,
        "drawdown_pct": round(dd, 2),
        "benchmark": journal.get("benchmark", "CDI+BOVA11 blend (paper)"),
        "computed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _write_json(PERF_PATH, report)
    return report


def graduation_eligibility(*, perf: dict[str, Any] | None = None) -> dict[str, Any]:
    """Checklist objetivo paper → live (configurável via env)."""
    perf = perf or compute_paper_performance()
    min_days = int(os.environ.get("FINANCE_GRADUATION_MIN_DAYS", "90"))
    min_trades = int(os.environ.get("FINANCE_GRADUATION_MIN_TRADES", "20"))
    min_win_rate = float(os.environ.get("FINANCE_GRADUATION_MIN_WIN_RATE", "45"))
    max_dd = float(os.environ.get("FINANCE_GRADUATION_MAX_DRAWDOWN", "12"))

    checks = {
        "min_trades": {
            "met": perf.get("trades_total", 0) >= min_trades,
            "detail": f"{perf.get('trades_total', 0)}/{min_trades} trades",
        },
        "win_rate": {
            "met": (perf.get("win_rate_pct") or 0) >= min_win_rate or perf.get("closed_round_trips", 0) < 5,
            "detail": f"win rate {perf.get('win_rate_pct', 0)}% (meta {min_win_rate}%)",
        },
        "drawdown": {
            "met": (perf.get("drawdown_pct") or 0) <= max_dd,
            "detail": f"drawdown {perf.get('drawdown_pct', 0)}% (max {max_dd}%)",
        },
        "window": {
            "met": perf.get("window_days", 0) >= min(min_days, 90),
            "detail": f"janela {perf.get('window_days')}d (meta acumular {min_days}d)",
        },
    }

    from learning_agent.core import agent_external_completion

    ext = agent_external_completion.assess_external_completion("finance-lead")
    f10_ok = any(c.get("id") == "F10" and c.get("passed") for c in ext.get("criteria") or [])
    f11_ok = any(c.get("id") == "F11" and c.get("passed") for c in ext.get("criteria") or [])
    checks["f10_quotes"] = {"met": f10_ok, "detail": "F10 cotações frescas"}
    checks["f11_risk"] = {"met": f11_ok, "detail": "F11 motor de risco"}

    missing = [k for k, v in checks.items() if not v.get("met")]
    return {
        "eligible": len(missing) == 0,
        "checks": checks,
        "missing": missing,
        "performance": perf,
        "note": "Graduação paper→live — não habilita ordens reais automaticamente",
    }


def format_performance_telegram(report: dict[str, Any] | None = None) -> str:
    r = report or compute_paper_performance()
    g = graduation_eligibility(perf=r)
    lines = [
        "Finance-lead — performance paper",
        f"Janela: {r.get('window_days')}d | trades: {r.get('trades_in_window')}/{r.get('trades_total')}",
        f"PnL fechado: R$ {r.get('pnl_brl', 0):+.2f} | win rate: {r.get('win_rate_pct')}%",
        f"Drawdown: {r.get('drawdown_pct')}%",
        f"Graduação live: {'OK' if g.get('eligible') else 'pendente'}",
    ]
    if g.get("missing"):
        lines.append("Falta: " + ", ".join(g["missing"][:4]))
    return "\n".join(lines)
