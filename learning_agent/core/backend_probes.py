"""Probes externos — backend-lead (B1–B5)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from learning_agent.config import PROJECT_ROOT

BACKEND_ROOT = PROJECT_ROOT / "agents" / "projects" / "backend-lead"
DEPLOY_DOC = BACKEND_ROOT / "docs" / "deploy.md"
ROUTES_DOC = BACKEND_ROOT / "docs" / "api-routes.md"
SPRINT_TEST = PROJECT_ROOT / "tests" / "agent_sprints" / "test_sprint_backend_lead_core.py"


def _result(passed: bool, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"passed": passed, "detail": detail, **extra}


def probe_backend_health_ok() -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient
        from learning_agent.api import app

        r = TestClient(app).get("/health")
        ok = r.status_code == 200 and r.json().get("status") == "ok"
        return _result(ok, f"status={r.status_code} body={r.json() if ok else r.text[:80]}")
    except Exception as exc:
        return _result(False, str(exc)[:200])


def probe_backend_openapi_available() -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient
        from learning_agent.api import app

        r = TestClient(app).get("/openapi.json")
        if r.status_code != 200:
            return _result(False, f"openapi status={r.status_code}")
        data = r.json()
        paths = data.get("paths") or {}
        return _result(len(paths) > 5, f"{len(paths)} paths no OpenAPI")
    except Exception as exc:
        return _result(False, str(exc)[:200])


def probe_backend_sprint_tests() -> dict[str, Any]:
    if not SPRINT_TEST.is_file():
        return _result(False, "sprint test ausente")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(SPRINT_TEST), "-q", "--tb=no"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    return _result(proc.returncode == 0, proc.stdout[-200:] or proc.stderr[-200:])


def probe_backend_deploy_doc() -> dict[str, Any]:
    if not DEPLOY_DOC.is_file():
        return _result(False, "deploy.md ausente")
    text = DEPLOY_DOC.read_text(encoding="utf-8").lower()
    needed = ["health", "env", "run"]
    missing = [k for k in needed if k not in text]
    if missing:
        return _result(False, f"faltam seções: {', '.join(missing)}")
    return _result(True, "deploy.md OK")


def probe_backend_api_routes_doc() -> dict[str, Any]:
    if not ROUTES_DOC.is_file():
        return _result(False, "api-routes.md ausente")
    text = ROUTES_DOC.read_text(encoding="utf-8")
    api_hits = text.count("/api/")
    return _result(api_hits >= 5, f"{api_hits} rotas /api/ listadas")


PROBE_REGISTRY: dict[str, Any] = {
    "backend_health_ok": probe_backend_health_ok,
    "backend_openapi_available": probe_backend_openapi_available,
    "backend_sprint_tests": probe_backend_sprint_tests,
    "backend_deploy_doc": probe_backend_deploy_doc,
    "backend_api_routes_doc": probe_backend_api_routes_doc,
}
