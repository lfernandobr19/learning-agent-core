"""Smoke tests — ecossistema multi-agente e IDE."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from learning_agent import db
from learning_agent.api import app
from learning_agent.config import PROJECT_ROOT, SQLITE_PATH

client = TestClient(app)


def test_health_smoke():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_agents_list_smoke():
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    projects = data.get("projects", data.get("agents", []))
    names = {p.get("name") for p in projects}
    assert "backend-lead" in names
    assert "reliability-lead" in names


def test_evolution_endpoint_smoke():
    r = client.get("/api/agents/evolution")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert len(data.get("agents", [])) >= 1


def test_progress_dashboard_smoke():
    r = client.get("/api/agents/progress-dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    assert "agents" in data
    assert "action_timeline" in data
    names = {a["agent"] for a in data["agents"]}
    assert "finance-lead" in names


def test_theater_messages_unique_ids():
    r = client.get("/api/theater/messages", params={"limit": 50})
    assert r.status_code == 200
    msgs = r.json().get("messages", [])
    ids = [m.get("id") for m in msgs if m.get("id")]
    assert len(ids) == len(set(ids))


def test_sqlite_indexes_present():
    db.init_db()
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in rows}
    assert "idx_notes_created" in names
    assert "idx_agent_insights_from" in names


def test_agent_sprint_tests_on_disk():
    sprint_dir = PROJECT_ROOT / "tests" / "agent_sprints"
    expected = [
        "test_sprint_backend_lead_core.py",
        "test_sprint_frontend_lead_core.py",
        "test_sprint_qa_guardian_core.py",
        "test_sprint_data_engineer_core.py",
        "test_sprint_reliability_lead_core.py",
    ]
    for name in expected:
        assert (sprint_dir / name).is_file()
