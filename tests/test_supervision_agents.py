"""Testes do painel de supervisão multi-agente."""

from learning_agent.core.supervision_agents import (
    SUPERVISOR_ROSTER,
    SupervisionContext,
    roster_summary,
    supervision_messages,
)


def test_roster_includes_all_supervisors():
    roles = {a["role"] for a in SUPERVISOR_ROSTER}
    assert roles == {
        "cursor",
        "architect",
        "senior-fe",
        "senior-be",
        "reviewer",
        "mentor",
        "quiz-master",
    }


def test_supervision_messages_covers_every_agent():
    ctx = SupervisionContext(
        level="Fase 1",
        topic="Explorer",
        process="qa",
        mentor_directive="Ravenna: valide jail path.",
        reviewer_focus="403 esperado em tools bloqueadas.",
        track_id="pytest-workspace",
    )
    msgs = supervision_messages(ctx)
    assert len(msgs) == len(SUPERVISOR_ROSTER)
    labels = {m[1] for m in msgs}
    assert "Cursor" in labels
    assert "Quiz Master" in labels
    assert any("Ravenna" in m[2] for m in msgs)


def test_roster_summary_markdown_table():
    summary = roster_summary()
    assert "| Cursor |" in summary
    assert "| Quiz Master |" in summary
