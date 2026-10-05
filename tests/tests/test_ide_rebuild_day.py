"""Testes — ide_rebuild_day orchestrator."""

from __future__ import annotations

from learning_agent.core import ide_rebuild_day


def test_load_week_plan_has_day_1():
    plan = ide_rebuild_day.load_week_plan()
    days = plan.get("days") or []
    assert any(int(d.get("day", 0)) == 1 for d in days)


def test_build_cursor_prompt_day_1():
    day = ide_rebuild_day.get_day_plan(1)
    assert day is not None
    prompt = ide_rebuild_day.build_cursor_prompt(day)
    assert "frontend-lead" in prompt or "Workbench" in prompt
    assert "CommandPalette" in prompt or "command_palette" in prompt.lower()


def test_check_day_acceptance_files():
    day = ide_rebuild_day.get_day_plan(1)
    acc = ide_rebuild_day.check_day_acceptance(day)
    assert acc.get("day") == 1
    assert "CommandPalette.tsx" in acc.get("checks", {})
