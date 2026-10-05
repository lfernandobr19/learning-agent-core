"""Testes — autonomia dos agentes."""

from __future__ import annotations

import shutil

import pytest

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_autonomy, agent_factory

PEER_A = "auto-agent-a"
PEER_B = "auto-agent-b"


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


def test_pick_autonomy_action():
    action = agent_autonomy.pick_autonomy_action(1)
    assert action in agent_autonomy.AUTONOMY_ACTIONS


def test_peer_question_session():
    result = agent_autonomy.run_peer_question_session(
        PEER_A, PEER_B, broadcast_observer=False
    )
    assert result["success"] is True
    assert result["question"]
    assert result["answer"]
    assert result["asker"] == PEER_A
    assert result["answerer"] == PEER_B


def test_consult_ravenna():
    result = agent_autonomy.agent_consult_ravenna(
        PEER_A, "Como integro API com a UI?", broadcast_observer=False
    )
    assert result["success"] is True
    assert result["reply"]


def test_collab_dev_sprint():
    result = agent_autonomy.run_collab_dev_sprint(
        "mini health-check endpoint", broadcast_observer=False
    )
    assert result["success"] is True
    assert result["plan"]
    assert (PROJECT_ROOT / result["sprint_file"]).is_file()


def test_execute_autonomy_cycle():
    action = agent_autonomy.pick_autonomy_action(5)
    result = agent_autonomy.execute_autonomy_action(action, topic="teste rápido")
    assert result.get("success") is not False


def test_should_run_consolidation():
    from learning_agent.core import agent_learning_loop

    assert agent_learning_loop.should_run_consolidation(12) is True
    assert agent_learning_loop.should_run_consolidation(11) is False
