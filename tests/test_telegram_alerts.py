"""Testes — alertas Telegram (mock)."""

from __future__ import annotations

from learning_agent.core import telegram_alerts


def test_telegram_alert_disabled_without_token(monkeypatch):
    monkeypatch.setattr(telegram_alerts, "TELEGRAM_BOT_TOKEN", "")
    out = telegram_alerts.send_alert("teste")
    assert out["sent"] is False


def test_alert_prove_report_no_go(monkeypatch):
    sent: list[str] = []

    def _fake_send(message: str, **kwargs):
        sent.append(message)
        return {"sent": True, "detail": "mock"}

    monkeypatch.setattr(telegram_alerts, "send_alert", _fake_send)
    report = {
        "agent": "finance-lead",
        "external": {"external_ready": False, "passed_count": 2, "total": 5},
        "blind_runs": [{"success": True, "passed": False, "blind_id": "blind_01", "composite": 50}],
    }
    out = telegram_alerts.alert_prove_report(report)
    assert out["sent"] is True
    assert "FALHOU" in sent[0]
