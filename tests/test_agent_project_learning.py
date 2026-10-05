"""Testes — aprendizado por projeto (gemma4-raven)."""
from __future__ import annotations

from learning_agent.core import agent_project_learning


def test_record_and_list_lessons(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_project_learning, "PROJECT_LEARNING_DIR", tmp_path)
    monkeypatch.setattr(
        agent_project_learning.errors,
        "record_failure",
        lambda *a, **k: {"ok": True},
    )

    agent_project_learning.record_lesson(
        "ravenna-home",
        error="pytest falhou: ModuleNotFoundError em homeassistant client",
        fix="adicionar homeassistant.py com mock e import relativo no test",
        phase="e2",
    )
    lessons = agent_project_learning.list_lessons("ravenna-home")
    assert len(lessons) == 1
    assert lessons[0]["utility"] >= 0.28

    block = agent_project_learning.format_lessons_block("ravenna-home")
    assert "MEMÓRIA DO PROJETO" in block


def test_skips_low_utility_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_project_learning, "PROJECT_LEARNING_DIR", tmp_path)
    out = agent_project_learning.record_lesson(
        "ravenna-home",
        error="falha",
        fix="",
        phase="autonomy",
    )
    assert out.get("skipped") is True


def test_compound_synthesis(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_project_learning, "PROJECT_LEARNING_DIR", tmp_path)
    monkeypatch.setattr(
        agent_project_learning.errors,
        "record_failure",
        lambda *a, **k: {"ok": True},
    )
    for i in range(2):
        agent_project_learning.record_lesson(
            "ravenna-home",
            error=f"workspace mount missing on attempt {i}",
            fix="sync pc-workspace antes de auto_apply",
            phase=f"e{i}",
            force=True,
        )
    compounds = agent_project_learning.synthesize_compound_lessons("ravenna-home", persist=True)
    assert compounds or any(
        r.get("kind") == "compound"
        for r in agent_project_learning.list_lessons("ravenna-home", limit=20, min_utility=0.0)
    )


def test_record_from_autonomy_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_project_learning, "PROJECT_LEARNING_DIR", tmp_path)
    monkeypatch.setattr(
        agent_project_learning.errors,
        "record_failure",
        lambda *a, **k: {"ok": True},
    )
    autonomy = {
        "passed": False,
        "attempts": [
            {
                "phase": "repair-1",
                "validation": {"failures": ["pytest failed: 0 tests collected"]},
                "checklist": {"failures": ["README missing"]},
                "critique": {"repairPrompt": "add README with setup steps"},
            }
        ],
    }
    recorded = agent_project_learning.record_from_autonomy(
        "test-proj",
        message="build app",
        autonomy=autonomy,
        phase="e2",
    )
    assert recorded is not None
    assert recorded.get("success")
