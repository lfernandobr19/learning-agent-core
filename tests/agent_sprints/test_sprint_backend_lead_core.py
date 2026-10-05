"""Sprint real — backend-lead: API FastAPI."""
from fastapi.testclient import TestClient

from learning_agent.api import app


def test_sprint_backend_lead_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
