"""Testes — tools autonomia finance-lead (F10/F11, risco, performance)."""

from __future__ import annotations

from learning_agent.core import finance_paper_performance, finance_quote_verify, finance_risk_engine


def test_risk_rejects_oversized_buy():
    portfolio = {"cash_brl": 5_000.0, "positions": []}
    decision = {
        "action": "buy",
        "ticker": "PETR4",
        "qty": 200,
        "price": 40.0,
        "asset_class": "acoes_br",
    }
    result = finance_risk_engine.check_order(decision, portfolio)
    assert not result["passed"]
    assert result.get("violations")


def test_risk_accepts_small_buy():
    portfolio = {"cash_brl": 100_000.0, "positions": []}
    decision = {
        "action": "buy",
        "ticker": "BOVA11",
        "qty": 10,
        "price": 120.0,
        "asset_class": "etf_br",
    }
    result = finance_risk_engine.check_order(decision, portfolio)
    assert result["passed"], result.get("detail")


def test_quote_verify_fixture_fresh():
    result = finance_quote_verify.verify_quote(
        "PETR4",
        38.5,
        data_source="fixture",
        manifest_age_hours=1.0,
    )
    assert result["passed"], result.get("detail")


def test_quote_verify_rejects_bad_price():
    result = finance_quote_verify.verify_quote("PETR4", 0)
    assert not result["passed"]


def test_probe_risk_engine():
    probe = finance_risk_engine.probe_risk_rejects_oversized_order()
    assert probe["passed"], probe.get("detail")


def test_paper_performance_report():
    report = finance_paper_performance.compute_paper_performance(days=365)
    assert report.get("success")
    assert "trades_total" in report
    assert report["trades_total"] >= 10


def test_graduation_eligibility_shape():
    grad = finance_paper_performance.graduation_eligibility()
    assert "eligible" in grad
    assert "checks" in grad
    assert "missing" in grad
