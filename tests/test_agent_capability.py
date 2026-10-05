"""Testes — níveis de capacidade dos agentes."""

from __future__ import annotations

import shutil

import pytest

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_autonomy, agent_capability, agent_factory

PEER = "cap-agent-test"


def _cleanup(slug: str) -> None:
    for path in [
        PROJECT_ROOT / ".cursor" / "agents" / f"{slug}.md",
        PROJECT_ROOT / "agents" / "projects" / slug,
        PROJECT_ROOT / ".cursor" / "skills" / f"{slug}-learning",
    ]:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def setup_agent():
    agent_factory.scaffold_agent_project(
        PEER, "backend", "test", focus="APIs", overwrite=True
    )
    yield
    _cleanup(PEER)


def test_capability_scale_has_level_5():
    assert 5 in agent_capability.CAPABILITY_SCALE
    assert agent_capability.CAPABILITY_SCALE[5]["label"] == "Especialista"


def test_capability_scale_has_level_6():
    assert 6 in agent_capability.CAPABILITY_SCALE
    assert "Paridade" in agent_capability.CAPABILITY_SCALE[6]["label"]


def test_level_6_from_parity(monkeypatch):
    monkeypatch.setattr(
        agent_capability,
        "_base_metrics",
        lambda _slug: {
            "manifest": {"display_name": "Test"},
            "gaps": {"gaps": [], "gap_count": 0, "covered": []},
            "gap_count": 0,
            "topics_covered": 0,
            "insights_shared": 0,
            "exchanges": 0,
            "notes": 0,
            "learning_closures": 0,
            "elevations": 0,
            "base_score": 40.0,
        },
    )
    monkeypatch.setattr(
        agent_capability,
        "_level_6_status",
        lambda _slug: {
            "eligible": True,
            "assessed": True,
            "parity_met": True,
            "composite_score": 88.0,
            "min_score": 80,
            "dimensions": {},
            "weak_dimensions": [],
            "missing": [],
        },
    )
    monkeypatch.setattr(
        agent_capability,
        "_level_5_checklist",
        lambda _slug, _m: {"eligible": False, "missing": ["zero_gaps"], "checks": {}},
    )
    result = agent_capability.compute_agent_capability("qa-guardian")
    assert result["level"] == 6
    assert result["level_label"] == "Paridade Cursor"
    assert result["score"] == 88.0


def test_compute_agent_capability():
    result = agent_capability.compute_agent_capability("backend-lead")
    assert result["success"] is True
    assert 1 <= result["level"] <= 6
    assert "level_5" in result
    assert "level_6" in result
    assert "checks" in result["level_5"]
    assert "next_actions" in result


def test_assess_ecosystem():
    report = agent_capability.assess_ecosystem(agents=["backend-lead", PEER])
    assert report["success"] is True
    assert len(report["agents"]) == 2
    assert "summary" in report
    assert "recommended_increments" in report


def test_pick_level_up_action_returns_known_action():
    action = agent_capability.pick_level_up_action(4)
    assert action is None or action in agent_autonomy.AUTONOMY_ACTIONS
