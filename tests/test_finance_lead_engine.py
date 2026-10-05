"""Testes — motor finance-lead."""

from __future__ import annotations

from learning_agent.core import finance_lead_engine


def test_build_training_status():
    status = finance_lead_engine.build_training_status()
    assert status["agent"] == "finance-lead"
    assert status["quality_mode"] is True
    assert "capability_level" in status
    assert "motor" in status


def test_web_research_skip_even_cycle():
    out = finance_lead_engine.run_web_research("Selic e IPCA", cycle_n=2)
    assert out.get("skipped") is True


def test_run_finance_practice_backtest():
    practice = finance_lead_engine.run_finance_practice("knowledge", "juros compostos")
    assert practice.get("action") == "finance_practice"
    assert "backtest" in practice
