"""Testes — reply Telegram para decisões paper."""

from __future__ import annotations

import json

from learning_agent.core import finance_telegram_replies as ftr


def test_parse_decision_reply():
    assert ftr.parse_decision_reply("sim") == "approve"
    assert ftr.parse_decision_reply("aprovo") == "approve"
    assert ftr.parse_decision_reply("registrar") == "register"
    assert ftr.parse_decision_reply("não") == "reject"
    assert ftr.parse_decision_reply("oi ravenna") is None


def test_extract_seq_from_text():
    assert ftr.extract_seq_from_text("Finance-lead\nID: #3\nAcao: buy") == "3"


def test_handle_decision_reply_approve(tmp_path, monkeypatch):
    from learning_agent.core import finance_decision_loop as fdl

    pending = tmp_path / "pending.json"
    journal = tmp_path / "journal.json"
    portfolio = tmp_path / "portfolio.json"
    registry = tmp_path / "registry.json"
    journal.write_text(
        json.dumps({"agent": "finance-lead", "trades": [], "benchmark": "x"}),
        encoding="utf-8",
    )
    pending.write_text(
        json.dumps(
            {
                "pending": [
                    {
                        "decision_id": "dec-test-1",
                        "seq": 2,
                        "action": "watch",
                        "ticker": "BOVA11",
                        "data_complete": True,
                        "validation": {"passed": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seq_state = tmp_path / "seq_state.json"
    monkeypatch.setattr(fdl, "PENDING_PATH", pending)
    monkeypatch.setattr(fdl, "JOURNAL_PATH", journal)
    monkeypatch.setattr(fdl, "PORTFOLIO_PATH", portfolio)
    monkeypatch.setattr(fdl, "SEQ_STATE_PATH", seq_state)
    monkeypatch.setattr(ftr, "REGISTRY_PATH", registry)

    reply_to = {"message_id": 999, "text": "Finance-lead — decisao paper\nID: #2"}
    ftr.register_decision_message(message_id=999, chat_id=1, seq=2, decision_id="dec-test-1")
    out = ftr.handle_decision_reply(reply_to, "sim")
    assert out and "OK" in out
