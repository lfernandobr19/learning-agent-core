"""Testes — probes externos finance-lead (F1–F5)."""

from __future__ import annotations

from learning_agent.core import agent_external_completion, finance_probes


def test_f1_backtest_reproducible():
    result = finance_probes.probe_finance_backtest_reproducible()
    assert result["passed"], result.get("detail")


def test_f2_monthly_report():
    result = finance_probes.probe_finance_monthly_report()
    assert result["passed"], result.get("detail")


def test_f3_paper_journal():
    result = finance_probes.probe_finance_paper_journal()
    assert result["passed"], result.get("detail")


def test_f4_ticker_validation():
    result = finance_probes.probe_finance_ticker_validation()
    assert result["passed"], result.get("detail")


def test_f5_uncertainty_decision():
    result = finance_probes.probe_finance_uncertainty_decision()
    assert result["passed"], result.get("detail")


def test_f6_cross_validation():
    result = finance_probes.probe_finance_backtest_cross_validation()
    assert result["passed"], result.get("detail")


def test_f7_diversified_data():
    from learning_agent.core import finance_training_extensions

    finance_training_extensions.run_diversified_data_fetch(source="fixture")
    result = finance_probes.probe_finance_diversified_data()
    assert result["passed"], result.get("detail")


def test_f8_economic_news():
    from learning_agent.core import finance_economic_news

    finance_economic_news.fetch_and_index_economic_news(use_web_fallback=False)
    result = finance_probes.probe_finance_economic_news_indexed()
    assert result["passed"], result.get("detail")


def test_f9_microeconomics():
    from learning_agent.core import finance_training_extensions

    finance_training_extensions.ensure_microeconomics_indexed(sync_cloud=False)
    result = finance_probes.probe_finance_microeconomics_content()
    assert result["passed"], result.get("detail")


def test_f10_quote_freshness():
    from learning_agent.core import finance_training_extensions

    finance_training_extensions.run_diversified_data_fetch(source="fixture")
    result = finance_probes.probe_finance_quote_freshness()
    assert result["passed"], result.get("detail")


def test_f11_risk_engine():
    result = finance_probes.probe_finance_risk_engine()
    assert result["passed"], result.get("detail")


def test_external_completion_finance_ready():
    report = agent_external_completion.assess_external_completion("finance-lead")
    assert report["success"]
    assert report["passed_count"] >= report["min_pass"]
    assert report["external_ready"]
