"""Testes — objetivo norte da IDE (paridade Cursor)."""

from __future__ import annotations

from learning_agent.core import ide_objectives


def test_assess_completion_structure():
    report = ide_objectives.assess_completion(run_slow_probes=False)
    assert report["success"] is True
    assert report["complete"] is False
    assert "north_star" in report
    assert report["summary"]["cursor_parity_pct"] < 100
    assert report["summary"]["must_total"] >= 20
    assert report.get("next_objective")


def test_north_star_mentions_cursor():
    assert "Cursor" in ide_objectives.NORTH_STAR


def test_get_next_objective_when_incomplete():
    nxt = ide_objectives.get_next_objective()
    assert nxt["success"] is True
    assert nxt.get("complete") is False
    assert nxt.get("objective", {}).get("id")


def test_curriculum_file_exists():
    from learning_agent.core import agent_curriculum

    cur = agent_curriculum.load_agent_curriculum("ide-completion")
    assert cur["success"] is True
    assert cur.get("north_star")
