"""Testes — finance_decision_loop."""

from __future__ import annotations

import json

import pytest

from learning_agent.core import finance_decision_loop as fdl


def test_load_market_context_has_tickers():
    ctx = fdl.load_market_context()
    assert ctx.get("success")
    assert len(ctx.get("tickers", [])) >= 4


def test_generate_l6_decision_structure():
    market = fdl.load_market_context()
    news = fdl.load_news_context()
    dec = fdl.generate_l6_decision(market, news)
    assert dec.get("decision_id")
    assert dec.get("action") in {"buy", "sell", "hold", "watch"}
    assert dec.get("thesis")
    assert dec.get("invalidation")


def test_validate_probes_passes_for_fixture():
    market = fdl.load_market_context()
    dec = fdl.generate_l6_decision(market, fdl.load_news_context())
    val = fdl.validate_decision_probes(dec)
    assert val.get("passed"), val


def test_pending_and_register_flow(tmp_path, monkeypatch):
    journal = tmp_path / "paper_journal.json"
    pending = tmp_path / "pending.json"
    seq_state = tmp_path / "seq_state.json"
    journal.write_text(
        json.dumps({"agent": "finance-lead", "trades": [], "benchmark": "test"}),
        encoding="utf-8",
    )
    pending.write_text(json.dumps({"pending": []}), encoding="utf-8")
    monkeypatch.setattr(fdl, "JOURNAL_PATH", journal)
    monkeypatch.setattr(fdl, "PENDING_PATH", pending)
    monkeypatch.setattr(fdl, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    monkeypatch.setattr(fdl, "SEQ_STATE_PATH", seq_state)

    market = fdl.load_market_context()
    dec = fdl.generate_l6_decision(market, fdl.load_news_context())
    val = fdl.validate_decision_probes(dec)
    entry = fdl.save_pending_decision(dec, val)
    assert entry.get("seq") == 1
    assert fdl.list_pending_decisions()

    if dec.get("action") in {"buy", "sell"} and dec.get("ticker"):
        result = fdl.approve_decision("1", mode="register")
        assert result.get("success"), result
        assert result.get("seq") == 1
        saved = json.loads(journal.read_text(encoding="utf-8"))
        assert len(saved.get("trades", [])) >= 1


def test_format_paper_portfolio():
    text = fdl.format_paper_portfolio()
    assert "Carteira paper" in text
    assert "Caixa" in text


def test_summarize_decision_plain_buy():
    market = fdl.load_market_context()
    dec = fdl.generate_l6_decision(market, fdl.load_news_context())
    summary = fdl.summarize_decision_plain(dec)
    assert summary
    if dec.get("action") == "buy":
        assert dec.get("ticker", "") in summary
        assert "compra" in summary.lower() or "Sugiro" in summary


def test_select_skips_held_ticker():
    market = {
        "tickers": [
            {"ticker": "PETR4", "signal": "bullish", "momentum_pct": 5.0, "asset_class": "acoes_br"},
            {"ticker": "HGLG11", "signal": "bullish", "momentum_pct": 3.0, "asset_class": "fii"},
            {"ticker": "MXRF11", "signal": "bullish", "momentum_pct": 2.0, "asset_class": "fii"},
        ]
    }
    pf = fdl._load_portfolio()
    original_positions = list(pf.get("positions") or [])
    try:
        pf["positions"] = [{"ticker": "PETR4", "qty": 100, "avg_price": 47.2}]
        fdl._write_json(fdl.PORTFOLIO_PATH, pf)
        pick, _ = fdl._select_bullish_candidate(market)
        assert pick is not None
        assert pick["ticker"] != "PETR4"
    finally:
        pf["positions"] = original_positions
        fdl._write_json(fdl.PORTFOLIO_PATH, pf)


def test_select_all_held_returns_none():
    market = {
        "tickers": [
            {"ticker": "PETR4", "signal": "bullish", "momentum_pct": 5.0, "asset_class": "acoes_br"},
        ]
    }
    pf = fdl._load_portfolio()
    original_positions = list(pf.get("positions") or [])
    try:
        pf["positions"] = [{"ticker": "PETR4", "qty": 50, "avg_price": 47.2}]
        fdl._write_json(fdl.PORTFOLIO_PATH, pf)
        pick, note = fdl._select_bullish_candidate(market)
        assert pick is None
        assert note
    finally:
        pf["positions"] = original_positions
        fdl._write_json(fdl.PORTFOLIO_PATH, pf)


def test_format_pick_ranking():
    decision = {
        "ticker": "HGLG11",
        "pick_ranking": [
            {"ticker": "VALE3", "asset_class": "ação BR", "momentum_pct": 3.0, "flags": ["sinal bullish"]},
            {"ticker": "HGLG11", "asset_class": "FII", "momentum_pct": 2.0, "flags": ["sinal bullish"]},
        ],
    }
    text = fdl.format_pick_ranking(decision)
    assert "VALE3" in text
    assert "★" in text
    assert "HGLG11" in text


def test_should_skip_duplicate_watch_notify(tmp_path, monkeypatch):
    notify_file = tmp_path / "last_notify.json"
    monkeypatch.setattr(fdl, "LAST_NOTIFY_PATH", notify_file)
    decision = {
        "action": "watch",
        "ticker": "IVVB11",
        "pick_ranking": [
            {"ticker": "IVVB11", "momentum_pct": 1.0, "signal": "neutral"},
            {"ticker": "PETR4", "momentum_pct": 0.5, "signal": "neutral"},
        ],
    }
    fdl._record_notify(decision)
    assert fdl._should_skip_watch_notify(decision) is True
    buy = {**decision, "action": "buy", "ticker": "PETR4"}
    assert fdl._should_skip_watch_notify(buy) is False


def test_resolve_short_id():
    fdl._bootstrap_seq_state()
    # PETR4 trade already in real portfolio maps to #1
    ref = fdl.resolve_decision_ref("1")
    if fdl._load_seq_state().get("by_seq"):
        assert ref is not None


def test_is_auto_paper_mode():
    assert fdl.is_auto_paper_mode("autonomous_paper")
    assert fdl.is_auto_paper_mode("autonomous")
    assert not fdl.is_auto_paper_mode("assisted")


def test_format_autonomous_decision_telegram_executed():
    decision = {
        "seq": 7,
        "decision_id": "dec-test",
        "action": "buy",
        "ticker": "VALE3",
        "qty": 10,
        "price": 62.5,
        "reason": "momentum",
        "thesis": "curto prazo",
    }
    validation = {"passed": True}
    commit = {"success": True, "portfolio_updated": True}
    text = fdl.format_autonomous_decision_telegram(decision, validation, commit)
    assert "AUTO executado" in text
    assert "#7" in text
    assert "VALE3" in text
    assert "/performance" in text


def test_format_autonomous_decision_telegram_blocked():
    decision = {"seq": 8, "decision_id": "dec-x", "action": "buy", "ticker": "VALE3"}
    validation = {"passed": True}
    commit = {"success": False, "error": "risk engine rejeitou ordem", "risk": {"detail": "caixa insuficiente"}}
    text = fdl.format_autonomous_decision_telegram(decision, validation, commit)
    assert "bloqueado" in text
    assert "caixa insuficiente" in text


def test_risk_engine_rejects_sell_without_position():
    from learning_agent.core import finance_risk_engine

    result = finance_risk_engine.check_order(
        {"action": "sell", "ticker": "VALE3", "qty": 10, "price": 60.0},
        {"cash_brl": 10_000.0, "positions": []},
    )
    assert result["passed"] is False
    assert "sem posição" in result["detail"]


def test_approve_sell_updates_paper_portfolio(tmp_path, monkeypatch):
    from learning_agent.core import finance_risk_engine

    journal = tmp_path / "paper_journal.json"
    pending = tmp_path / "pending.json"
    portfolio = tmp_path / "portfolio.json"
    seq_state = tmp_path / "seq_state.json"
    risk_state = tmp_path / "risk_state.json"
    journal.write_text(
        json.dumps({"agent": "finance-lead", "trades": [], "benchmark": "test"}),
        encoding="utf-8",
    )
    pending.write_text(json.dumps({"pending": []}), encoding="utf-8")
    portfolio.write_text(
        json.dumps({
            "agent": "finance-lead",
            "cash_brl": 1_000.0,
            "positions": [{"ticker": "VALE3", "qty": 20, "avg_price": 50.0, "asset_class": "acoes_br"}],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(fdl, "JOURNAL_PATH", journal)
    monkeypatch.setattr(fdl, "PENDING_PATH", pending)
    monkeypatch.setattr(fdl, "PORTFOLIO_PATH", portfolio)
    monkeypatch.setattr(fdl, "SEQ_STATE_PATH", seq_state)
    monkeypatch.setattr(finance_risk_engine, "JOURNAL_PATH", journal)
    monkeypatch.setattr(finance_risk_engine, "RISK_STATE_PATH", risk_state)
    monkeypatch.setattr(fdl, "validate_decision_probes", lambda decision: {"passed": True, "checks": {}})
    monkeypatch.setattr(
        fdl.agent_action_journal,
        "complete_action_cycle",
        lambda *args, **kwargs: {"success": True},
    )

    decision = {
        "decision_id": "dec-sell-test",
        "action": "sell",
        "side": "sell",
        "ticker": "VALE3",
        "qty": 5,
        "price": 62.0,
        "asset_class": "acoes_br",
        "data_complete": True,
        "thesis": "reduzir exposição paper",
        "invalidation": "N/A",
    }
    fdl.save_pending_decision(decision, {"passed": True})
    result = fdl.approve_decision("dec-sell-test", mode="approve")
    assert result["success"], result

    saved_portfolio = json.loads(portfolio.read_text(encoding="utf-8"))
    assert saved_portfolio["cash_brl"] == 1_310.0
    assert saved_portfolio["positions"] == [
        {"ticker": "VALE3", "qty": 15, "avg_price": 50.0, "asset_class": "acoes_br"}
    ]
