"""Testes — rubrica risk_section em blind exams."""

from __future__ import annotations

from learning_agent.core import agent_benchmarks
from learning_agent.core.finance_blind_exam import risk_section_present


def test_risk_section_accepts_volatility():
    assert risk_section_present('{"risk": "volatility elevated in macro scenario"}')
    assert risk_section_present('{"risk": "volatilidade elevada; drawdown max 10%"}')


def test_blind_03_volatility_response_scores_risk():
    response = {
        "data_source": "agents/projects/finance-lead/fixtures/PETR4_sample.csv",
        "action": "watch",
        "recommendation": "watch",
        "tickers": ["PETR4", "VALE3"],
        "risk": "volatility",
        "invalidation": "rompimento de suporte",
    }
    result = agent_benchmarks.run_blind("finance-lead", "blind_03", response=response)
    assert result["success"]
    risk_score = next(s for s in result["scores"] if s["id"] == "risk_section")
    assert risk_score["passed"]
