"""Testes — alertas blind batch."""

from __future__ import annotations

from learning_agent.core import telegram_alerts


def test_alert_blind_batch_ok(monkeypatch):
    sent = []

    def fake_send(msg, **kwargs):
        sent.append(msg)
        return {"sent": True}

    monkeypatch.setattr(telegram_alerts, "send_alert", fake_send)
    report = {
        "success": True,
        "pass_threshold": 80,
        "overall": {"mean_composite": 100, "total_fail": 0, "total_below_threshold": 0},
        "blinds": [{"blind_id": "blind_01", "mean_composite": 100, "min_composite": 100}],
    }
    out = telegram_alerts.alert_blind_batch(report, source="batch")
    assert out["sent"]
    assert "OK" in sent[0]


def test_alert_blind_batch_fail(monkeypatch):
    sent = []

    def fake_send(msg, **kwargs):
        sent.append(msg)
        return {"sent": True}

    monkeypatch.setattr(telegram_alerts, "send_alert", fake_send)
    report = {
        "success": False,
        "pass_threshold": 80,
        "overall": {"mean_composite": 75, "total_fail": 2, "total_below_threshold": 2},
        "blinds": [{"blind_id": "blind_03", "mean_composite": 75, "min_composite": 70}],
    }
    telegram_alerts.alert_blind_batch(report, source="batch")
    assert "ATENÇÃO" in sent[0]
