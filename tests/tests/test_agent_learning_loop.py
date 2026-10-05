"""Testes — loop de aprendizado autônomo (ações P0–P3)."""

from __future__ import annotations

import shutil

import pytest

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_autonomy, agent_factory, agent_learning_loop

PEER_A = "loop-agent-a"
PEER_B = "loop-agent-b"


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
def setup_agents():
    for spec in (
        (PEER_A, "backend", "APIs"),
        (PEER_B, "frontend", "UI"),
    ):
        agent_factory.scaffold_agent_project(
            spec[0], spec[1], f"Agente {spec[0]}", focus=spec[2], overwrite=True
        )
    yield
    _cleanup(PEER_A)
    _cleanup(PEER_B)


def test_autonomy_actions_expanded():
    assert "peer_quiz" in agent_autonomy.AUTONOMY_ACTIONS
    assert "ravenna_hands_on" in agent_autonomy.AUTONOMY_ACTIONS
    assert "debug_sweep" in agent_autonomy.AUTONOMY_ACTIONS
    assert "learning_closure" in agent_autonomy.AUTONOMY_ACTIONS
    assert len(agent_autonomy.AUTONOMY_ACTIONS) >= 26


def test_debug_sweep():
    result = agent_learning_loop.run_debug_sweep(broadcast_observer=False)
    assert result["success"] is True
    assert result["agent"] == "reliability-lead"
    assert "all_passed" in result


def test_agent_health_audit():
    result = agent_learning_loop.run_agent_health_audit(broadcast_observer=False)
    assert result["success"] is True
    assert "total_agents" in result
    arch_ids = [a.get("id") for a in agent_factory.list_archetypes().get("archetypes", [])]
    assert "debug-optimizer" in arch_ids


def test_pick_action_in_list():
    for cycle in range(1, 25):
        action = agent_autonomy.pick_autonomy_action(cycle)
        assert action in agent_autonomy.AUTONOMY_ACTIONS


def test_learning_closure_phases():
    result = agent_learning_loop.run_learning_closure(
        "test_action",
        "testes de autonomia",
        {"topic": "pytest"},
        agent=PEER_A,
        broadcast_observer=False,
    )
    assert result["success"] is True
    assert result["phases"] == ["understand", "test", "elevate"]
    assert result["understand"]
    assert result["quiz_id"]


def test_peer_quiz():
    result = agent_learning_loop.run_peer_quiz(
        PEER_A, PEER_B, broadcast_observer=False
    )
    assert result["success"] is True
    assert result["question"]
    assert result["evaluation"]


def test_graph_sync():
    result = agent_learning_loop.run_graph_sync(
        topic="multi-agent autonomy",
        broadcast_observer=False,
    )
    assert result["success"] is True
    assert result["edges_created"] >= 1


def test_proof_gate():
    result = agent_learning_loop.run_proof_gate(broadcast_observer=False)
    assert result["success"] is True
    assert "all_passed" in result
    assert result["suite"]["total"] >= 1


def test_error_roundtable_empty_ok():
    result = agent_learning_loop.run_error_roundtable(broadcast_observer=False)
    assert result["success"] is True


def test_ravenna_hands_on():
    result = agent_learning_loop.run_ravenna_hands_on(
        topic="testes autônomos",
        broadcast_observer=False,
    )
    assert result["success"] is True
    assert result["plan"]
    assert result.get("note_id")


def test_execute_dispatch():
    result = agent_autonomy.execute_autonomy_action(
        "graph_sync", topic="dispatch test"
    )
    assert result.get("success") is True
    assert result.get("action") == "graph_sync"
