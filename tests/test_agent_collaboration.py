"""Testes — colaboração e aprendizado entre agentes."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_collaboration, agent_factory

PEER_A = "collab-agent-a"
PEER_B = "collab-agent-b"


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
def setup_two_agents():
    for spec in (
        (PEER_A, "backend", "APIs"),
        (PEER_B, "frontend", "UI React"),
    ):
        agent_factory.scaffold_agent_project(
            spec[0], spec[1], f"Agente {spec[0]}", focus=spec[2], overwrite=True
        )
    yield
    _cleanup(PEER_A)
    _cleanup(PEER_B)


def test_share_and_get_peer_insights():
    shared = agent_collaboration.share_insight(
        PEER_A,
        "Padrão: routers finos, lógica em services.",
        "camadas FastAPI",
        to_agents=[PEER_B],
    )
    assert shared["success"] is True

    absorbed = agent_collaboration.get_peer_insights(PEER_B, limit=5)
    assert absorbed["success"] is True
    assert absorbed["count"] >= 1
    assert any(i["from_agent"] == PEER_A for i in absorbed["insights"])


def test_detect_knowledge_gaps():
    report = agent_collaboration.detect_knowledge_gaps(PEER_A)
    assert report["success"] is True
    assert "gaps" in report
    assert report["archetype"] == "backend"


def test_run_roundtable():
    result = agent_collaboration.run_agent_roundtable(
        "contratos entre backend e frontend",
        agents=[PEER_A, PEER_B],
        max_rounds=1,
    )
    assert result["success"] is True
    assert len(result["dialogue"]) == 2
    assert result["ravenna_synthesis"]


def test_consolidate_requires_agents():
    result = agent_collaboration.consolidate_agent_ecosystem(
        agents=[PEER_A, PEER_B],
        research_gaps=False,
        run_roundtable=True,
    )
    assert result["success"] is True
    assert result["master_note_id"]


def test_active_collaboration_start_stop():
    import asyncio

    async def _run():
        started = await agent_collaboration.start_active_collaboration(interval_seconds=60)
        assert started["success"] is True
        status = agent_collaboration.get_active_collaboration_status()
        assert status["running"] is True
        stopped = await agent_collaboration.stop_active_collaboration()
        assert stopped["success"] is True
        assert agent_collaboration.get_active_collaboration_status()["running"] is False

    asyncio.run(_run())


def test_api_collaboration_endpoints():
    with TestClient(app) as client:
        share = client.post(
            "/api/agents/collaborate/share",
            json={
                "from_agent": PEER_B,
                "insight": "Usar Error Boundary em painéis críticos.",
                "topic": "resiliência UI",
                "to_agents": [PEER_A],
            },
        )
        assert share.status_code == 200
        assert share.json()["success"] is True

        insights = client.get(f"/api/agents/collaborate/peers/{PEER_A}/insights")
        assert insights.status_code == 200

        gaps = client.get(f"/api/agents/collaborate/gaps/{PEER_A}")
        assert gaps.status_code == 200

        rt = client.post(
            "/api/agents/collaborate/roundtable",
            json={"topic": "testes e2e", "agents": [PEER_A, PEER_B]},
        )
        assert rt.status_code == 200
        assert rt.json()["success"] is True

        active = client.get("/api/agents/collaborate/active")
        assert active.status_code == 200

        start = client.post(
            "/api/agents/collaborate/active/start",
            json={"interval_seconds": 120},
        )
        assert start.status_code == 200
        stop = client.post("/api/agents/collaborate/active/stop")
        assert stop.status_code == 200
