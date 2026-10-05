"""Sprint real — qa-guardian: rotas críticas."""
from fastapi.testclient import TestClient

from learning_agent.api import app


def test_sprint_qa_guardian_agents_route():
    client = TestClient(app)
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    names = {a.get("name") for a in data.get("projects", data.get("agents", []))}
    assert "backend-lead" in names
