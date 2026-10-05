"""Motor de risco hard-limit — finance-lead (autonomia gradual)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
JOURNAL_PATH = FINANCE_ROOT / "data" / "paper_journal.json"
PORTFOLIO_PATH = FINANCE_ROOT / "data" / "paper_portfolio.json"
RISK_STATE_PATH = FINANCE_ROOT / "data" / "risk_state.json"


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


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


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_risk_state() -> dict[str, Any]:
    return _read_json(
        RISK_STATE_PATH,
        {"kill_switch": False, "reason": "", "updated_at": None, "trades_today": 0, "trade_date": ""},
    )


def save_risk_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _utcnow()
    _write_json(RISK_STATE_PATH, state)


def set_kill_switch(active: bool, *, reason: str = "") -> dict[str, Any]:
    state = load_risk_state()
    state["kill_switch"] = active
    state["reason"] = reason
    save_risk_state(state)
    return state


def is_kill_switch_active() -> tuple[bool, str]:
    manual = os.environ.get("FINANCE_KILL_SWITCH", "false").lower() in {"1", "true", "yes", "on"}
    if manual:
        return True, "FINANCE_KILL_SWITCH=true no .env"
    state = load_risk_state()
    if state.get("kill_switch"):
        return True, str(state.get("reason") or "kill switch ativo (risk_state)")
    return False, ""


def _portfolio_value(portfolio: dict[str, Any]) -> float:
    cash = float(portfolio.get("cash_brl") or 0)
    positions = portfolio.get("positions") or []
    pos_val = sum(float(p.get("qty") or 0) * float(p.get("avg_price") or 0) for p in positions)
    return cash + pos_val


def _position_pct(portfolio: dict[str, Any], ticker: str, order_value: float) -> float:
    total = _portfolio_value(portfolio) + order_value
    if total <= 0:
        return 100.0
    positions = portfolio.get("positions") or []
    existing = next((p for p in positions if str(p.get("ticker", "")).upper() == ticker.upper()), None)
    existing_val = float(existing.get("qty") or 0) * float(existing.get("avg_price") or 0) if existing else 0
    return (existing_val + order_value) / total * 100


def _class_exposure_pct(portfolio: dict[str, Any], asset_class: str, order_value: float) -> float:
    total = _portfolio_value(portfolio) + order_value
    if total <= 0:
        return 100.0
    class_val = order_value
    for p in portfolio.get("positions") or []:
        if str(p.get("asset_class") or "") == asset_class:
            class_val += float(p.get("qty") or 0) * float(p.get("avg_price") or 0)
    return class_val / total * 100


def _trades_today_count() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = load_risk_state()
    if state.get("trade_date") == today:
        return int(state.get("trades_today") or 0)
    journal = _read_json(JOURNAL_PATH, {"trades": []})
    count = 0
    for t in journal.get("trades") or []:
        ts = str(t.get("executed_at") or t.get("at") or "")
        if ts.startswith(today):
            count += 1
    return count


def record_trade_executed() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = load_risk_state()
    if state.get("trade_date") != today:
        state["trade_date"] = today
        state["trades_today"] = 0
    state["trades_today"] = int(state.get("trades_today") or 0) + 1
    save_risk_state(state)


def estimate_drawdown_pct(portfolio: dict[str, Any]) -> float:
    """Drawdown vs pico registrado em risk_state (atualizado a cada check)."""
    state = load_risk_state()
    current = _portfolio_value(portfolio)
    peak = float(state.get("portfolio_peak_brl") or current)
    if current > peak:
        peak = current
        state["portfolio_peak_brl"] = peak
        save_risk_state(state)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak * 100)


def check_order(
    decision: dict[str, Any],
    portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Valida ordem contra limites hard-coded. LLM não pode ultrapassar."""
    action = str(decision.get("action") or "").lower()
    if action not in {"buy", "sell"}:
        return {"passed": True, "detail": f"action={action} — sem check de risco"}

    kill, kill_reason = is_kill_switch_active()
    if kill:
        return {"passed": False, "detail": kill_reason, "kill_switch": True}

    portfolio = portfolio or _read_json(
        PORTFOLIO_PATH,
        {"cash_brl": 100_000.0, "positions": []},
    )

    max_pos_pct = _env_float("FINANCE_MAX_POSITION_PCT", 15.0)
    max_class_pct = _env_float("FINANCE_MAX_CLASS_PCT", 30.0)
    max_daily = _env_int("FINANCE_MAX_DAILY_TRADES", 3)
    max_dd = _env_float("FINANCE_MAX_PORTFOLIO_DRAWDOWN_PCT", 15.0)
    min_cash_pct = _env_float("FINANCE_MIN_CASH_PCT", 10.0)

    violations: list[str] = []

    dd = estimate_drawdown_pct(portfolio)
    if dd > max_dd:
        set_kill_switch(True, reason=f"drawdown {dd:.1f}% > {max_dd}%")
        violations.append(f"drawdown {dd:.1f}% — kill switch ON")

    if _trades_today_count() >= max_daily:
        violations.append(f"max trades/dia ({max_daily}) atingido")

    ticker = str(decision.get("ticker") or "").upper()
    qty = int(decision.get("qty") or 0)
    price = float(decision.get("price") or decision.get("last_close") or 0)
    order_value = qty * price
    if not ticker:
        violations.append("ticker obrigatório")
    if qty <= 0:
        violations.append("quantidade deve ser positiva")
    if price <= 0:
        violations.append("preço deve ser positivo")

    if action == "buy":
        cash = float(portfolio.get("cash_brl") or 0)
        if order_value > cash:
            violations.append(f"caixa insuficiente ({order_value:.0f} > {cash:.0f})")

        total_after = _portfolio_value(portfolio)
        cash_after = cash - order_value
        if total_after > 0 and (cash_after / total_after * 100) < min_cash_pct:
            violations.append(f"caixa pós-ordem < {min_cash_pct}%")

        pos_pct = _position_pct(portfolio, ticker, order_value)
        if pos_pct > max_pos_pct:
            violations.append(f"posição {ticker} {pos_pct:.1f}% > max {max_pos_pct}%")

        ac = str(decision.get("asset_class") or "")
        if ac:
            class_pct = _class_exposure_pct(portfolio, ac, order_value)
            if class_pct > max_class_pct:
                violations.append(f"classe {ac} {class_pct:.1f}% > max {max_class_pct}%")
    elif action == "sell":
        positions = portfolio.get("positions") or []
        held_qty = sum(
            int(p.get("qty") or 0)
            for p in positions
            if str(p.get("ticker", "")).upper() == ticker
        )
        if held_qty <= 0:
            violations.append(f"sem posição em {ticker}")
        elif qty > held_qty:
            violations.append(f"venda {qty} > posição {held_qty} em {ticker}")

    passed = len(violations) == 0
    return {
        "passed": passed,
        "detail": "; ".join(violations) if violations else "limites OK",
        "violations": violations,
        "drawdown_pct": round(dd, 2),
    }


def probe_risk_rejects_oversized_order() -> dict[str, Any]:
    """F11 probe — ordem que viola limite deve ser rejeitada."""
    portfolio = {
        "cash_brl": 10_000.0,
        "positions": [{"ticker": "PETR4", "qty": 100, "avg_price": 40.0, "asset_class": "acoes_br"}],
    }
    decision = {
        "action": "buy",
        "ticker": "VALE3",
        "qty": 500,
        "price": 60.0,
        "asset_class": "acoes_br",
    }
    result = check_order(decision, portfolio)
    if result.get("passed"):
        return {"passed": False, "detail": "ordem oversize deveria falhar"}
    return {"passed": True, "detail": result.get("detail", "rejeitada")}
