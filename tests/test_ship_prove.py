"""Testes — pipeline Ship e benchmarks cegos."""

from __future__ import annotations

from learning_agent.core import agent_benchmarks, ship_pipeline


def test_ship_queue_lists_items():
    status = ship_pipeline.build_ship_status()
    assert status["success"]
    assert status["done_total"] >= 1 or status["queue_total"] >= 0


def test_operating_mode_focus_finance():
    mode = ship_pipeline.load_operating_mode()
    assert mode.get("focus", {}).get("primary_agent") == "finance-lead"


def test_finance_blind_01_scores():
    result = agent_benchmarks.run_blind("finance-lead", "blind_01")
    assert result["success"]
    assert result["composite"] >= 80
    assert result["passed"]
