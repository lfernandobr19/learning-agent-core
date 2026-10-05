"""Testes — status finance-lead Telegram."""

from __future__ import annotations

from learning_agent.core import finance_status


def test_format_finance_message():
    msg = finance_status.format_finance_telegram_message(
        {
            "running": True,
            "external_pass": "5/5",
            "external_ready": True,
            "blind_score": 100.0,
            "level": 6,
            "score": 85,
            "last_cycle": 8,
            "criteria_fail": [],
        }
    )
    assert "Finance-lead" in msg
    assert "5/5" in msg
    assert "QUALIDADE" in msg


def test_is_finance_query():
    assert finance_status.is_finance_status_query("Como está o finance-lead?")
    assert not finance_status.is_finance_status_query("Qual a capital da França?")


def test_parse_until_iso():
    from datetime import datetime, timedelta

    from learning_agent.scripts import run_finance_lead_overnight as mod

    future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT05:30")
    target = mod._parse_until(future)
    assert target.hour == 5 and target.minute == 30
