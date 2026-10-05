"""Testes — diretivas de treino finance-lead via Telegram."""

from __future__ import annotations

import json

import pytest

from learning_agent.core import finance_training_directives as ftd


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    prompts = tmp_path / "overnight-prompts.yaml"
    prompts.write_text("teacher_topics: []\n", encoding="utf-8")
    playbook = tmp_path / "playbook.md"
    playbook.write_text("# Playbook\n", encoding="utf-8")

    monkeypatch.setattr(ftd, "DIRECTIVES_PATH", data / "training_directives.json")
    monkeypatch.setattr(ftd, "OVERRIDE_PATH", data / "directive_cycle_override.json")
    monkeypatch.setattr(ftd, "PROMPTS_PATH", prompts)
    monkeypatch.setattr(ftd, "PLAYBOOK_PATH", playbook)
    return tmp_path


def test_is_apply_request_with_finance_history(monkeypatch):
    from learning_agent.core import chat

    monkeypatch.setattr(
        chat,
        "_load_history",
        lambda channel, user_id, limit=8: [
            {"role": "user", "content": "Como melhorar o finance-lead?"},
            {"role": "assistant", "content": "Foque em reasoning e quiz SM-2."},
        ],
    )
    assert ftd.is_apply_request("aplica isso", channel="telegram", user_id="1")
    assert not ftd.is_apply_request("Qual a capital da França?")


def test_extract_heuristic_reasoning_and_quiz(monkeypatch):
    monkeypatch.setattr(ftd, "_extract_via_llm", lambda text: [])
    text = "Sugiro focar em reasoning e rodar quiz SM-2 esta semana."
    items = ftd.extract_directives(text)
    actions = {d["action"] for d in items}
    assert "prioritize_dimension" in actions
    assert "run_consolidation" in actions


def test_queue_and_apply_playbook(isolated_paths):
    queued = ftd.queue_directives(
        [{"action": "append_playbook_note", "text": "Priorizar macro BR no drill."}],
        requested_by="test",
    )
    assert len(queued) == 1
    result = ftd.apply_queued()
    assert result["applied"]
    assert "Priorizar macro BR" in isolated_paths.joinpath("playbook.md").read_text(encoding="utf-8")


def test_prioritize_dimension_override(isolated_paths):
    ftd.queue_directives(
        [{"action": "prioritize_dimension", "dimension": "reasoning", "cycles": 2}],
    )
    ftd.apply_queued()
    ov = ftd.get_cycle_overrides()
    assert ov["force_dimension"] == "reasoning"
    assert ov["remaining"] == 2
    ftd.tick_cycle_override()
    assert ftd.get_cycle_overrides()["remaining"] == 1


def test_add_teacher_topic(isolated_paths):
    ftd.queue_directives(
        [
            {
                "action": "add_teacher_topic",
                "topic": "Tributação FIIs 2026 — PF",
                "level": 4,
                "tags": ["finance", "fiis"],
            }
        ],
    )
    ftd.apply_queued()
    import yaml

    cfg = yaml.safe_load(isolated_paths.joinpath("overnight-prompts.yaml").read_text(encoding="utf-8"))
    assert any("Tributação FIIs" in t.get("topic", "") for t in cfg["teacher_topics"])
