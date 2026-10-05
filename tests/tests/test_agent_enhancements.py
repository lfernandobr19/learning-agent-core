"""Testes — incrementos de aprendizado (currículo, mentoria, IDE, eventos)."""

from __future__ import annotations

from learning_agent.core import (
    agent_curriculum,
    agent_event_triggers,
    agent_ide_practice,
    agent_mentoring,
    agent_spaced_review,
)


def test_list_curricula():
    result = agent_curriculum.list_curricula()
    assert result["success"] is True
    assert result["count"] >= 5


def test_next_milestone_backend():
    result = agent_curriculum.get_next_milestone("backend-lead")
    assert result["success"] is True
    assert result.get("suggested_actions")


def test_emit_and_consume_event():
    agent_event_triggers.emit_event("test_failed", detail="pytest demo", agent="qa-guardian")
    action = agent_event_triggers.pick_event_action()
    assert action == "error_roundtable"


def test_mentor_session():
    result = agent_mentoring.run_mentor_session(
        "backend-lead", "reliability-lead", broadcast_observer=False
    )
    assert result["success"] is True
    assert result["lesson"]


def test_spaced_review():
    result = agent_spaced_review.run_spaced_review("frontend-lead", broadcast_observer=False)
    assert result["success"] is True


def test_ide_improvement_sprint():
    result = agent_ide_practice.run_ide_improvement_sprint(
        "frontend-lead", broadcast_observer=False
    )
    assert result["success"] is True
    assert result.get("valid_practice") is True
    assert result.get("output_file")


def test_quiz_answer_evaluation():
    from learning_agent.core.agent_learning_loop import _evaluate_quiz_answer

    assert _evaluate_quiz_answer(
        "Interface HTTP que usa verbos padrão para manipular recursos.",
        "Uma API REST usa HTTP com verbos GET POST PUT DELETE para recursos.",
    )
    assert not _evaluate_quiz_answer("resposta longa esperada", "ok")
