"""Probes externos — frontend, qa, data, reliability (F/Q/D/R)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

FE_ROOT = PROJECT_ROOT / "ravenna-ide" / "frontend"
FE_PROJECT = PROJECT_ROOT / "agents" / "projects" / "frontend-lead"
QA_PROJECT = PROJECT_ROOT / "agents" / "projects" / "qa-guardian"
DATA_PROJECT = PROJECT_ROOT / "agents" / "projects" / "data-engineer"
REL_PROJECT = PROJECT_ROOT / "agents" / "projects" / "reliability-lead"

SPRINT_FRONTEND = PROJECT_ROOT / "tests" / "agent_sprints" / "test_sprint_frontend_lead_core.py"
SPRINT_QA = PROJECT_ROOT / "tests" / "agent_sprints" / "test_sprint_qa_guardian_core.py"
SPRINT_DATA = PROJECT_ROOT / "tests" / "agent_sprints" / "test_sprint_data_engineer_core.py"
SPRINT_RELIABILITY = PROJECT_ROOT / "tests" / "agent_sprints" / "test_sprint_reliability_lead_core.py"
SMOKE_TEST = PROJECT_ROOT / "tests" / "test_agent_ide_smoke.py"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ide-ci.yml"


def _result(passed: bool, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"passed": passed, "detail": detail, **extra}


def _run_pytest(path: Path, *, timeout: int = 120) -> dict[str, Any]:
    if not path.is_file():
        return _result(False, f"ausente: {path.name}")
    # RAVENNA_CAPABILITY_PROBE quebra a recursão: o subprocesso pytest pode
    # chamar /api/agents/evolution, que reavalia capability e re-executaria a
    # probe — o env var herdado interrompe esse ciclo.
    env = {**os.environ, "RAVENNA_CAPABILITY_PROBE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(path), "-q", "--tb=no"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return _result(proc.returncode == 0, proc.stdout[-200:] or proc.stderr[-200:])


def _file_contains(path: Path, *needles: str) -> dict[str, Any]:
    if not path.is_file():
        return _result(False, f"{path.name} ausente")
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    missing = [n for n in needles if n.lower() not in text]
    if missing:
        return _result(False, f"faltam: {', '.join(missing)}")
    return _result(True, f"{path.name} OK")


# --- frontend-lead (FE1–FE5) ---


def probe_frontend_sprint_core() -> dict[str, Any]:
    return _run_pytest(SPRINT_FRONTEND)


def probe_frontend_progress_dashboard() -> dict[str, Any]:
    path = FE_ROOT / "src" / "components" / "AgentProgressDashboard.tsx"
    return _file_contains(path, "progress-dashboard", "external")


def probe_frontend_distillation_panel() -> dict[str, Any]:
    path = FE_ROOT / "src" / "components" / "DistillationPanel.tsx"
    return _file_contains(path, "distillation", "pairs")


def probe_frontend_external_exams_panel() -> dict[str, Any]:
    path = FE_ROOT / "src" / "components" / "ExternalExamsPanel.tsx"
    return _file_contains(path, "external", "exam")


def probe_frontend_component_doc() -> dict[str, Any]:
    path = FE_PROJECT / "docs" / "component-checklist.md"
    return _file_contains(path, "vitest", "tsc", "a11y")


# --- qa-guardian (Q1–Q5) ---


def probe_qa_sprint_core() -> dict[str, Any]:
    return _run_pytest(SPRINT_QA)


def probe_qa_smoke_suite() -> dict[str, Any]:
    if not SMOKE_TEST.is_file():
        return _result(False, "test_agent_ide_smoke.py ausente")
    return _run_pytest(SMOKE_TEST, timeout=180)


def probe_qa_ci_workflow() -> dict[str, Any]:
    if not CI_WORKFLOW.is_file():
        return _result(False, "ide-ci.yml ausente")
    text = CI_WORKFLOW.read_text(encoding="utf-8").lower()
    ok = "pytest" in text and "vitest" in text
    return _result(ok, "pytest + vitest no CI")


def probe_qa_playbook_smoke() -> dict[str, Any]:
    path = QA_PROJECT / "playbook.md"
    return _file_contains(path, "smoke", "pytest")


def probe_qa_agents_registry() -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient
        from learning_agent.api import app

        r = TestClient(app).get("/api/agents")
        if r.status_code != 200:
            return _result(False, f"status={r.status_code}")
        data = r.json()
        names = {a.get("name") for a in data.get("projects", data.get("agents", []))}
        needed = {"finance-lead", "backend-lead", "qa-guardian"}
        missing = needed - names
        return _result(not missing, f"agentes={sorted(names)}" if not missing else f"faltam {sorted(missing)}")
    except Exception as exc:
        return _result(False, str(exc)[:200])


# --- data-engineer (D1–D5) ---


def probe_data_sprint_core() -> dict[str, Any]:
    return _run_pytest(SPRINT_DATA)


def probe_data_sqlite_indexes() -> dict[str, Any]:
    import sqlite3

    from learning_agent.config import SQLITE_PATH

    if not SQLITE_PATH.is_file():
        return _result(False, "sqlite ausente")
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in rows}
    ok = "idx_quiz_attempts_item" in names and "idx_agent_exchanges_thread" in names
    return _result(ok, f"{len(names)} indices idx_*")


def probe_data_hf_export() -> dict[str, Any]:
    train = PROJECT_ROOT / "data" / "training" / "hf_sft" / "train.jsonl"
    if not train.is_file():
        return _result(False, "train.jsonl ausente")
    lines = sum(1 for _ in train.open(encoding="utf-8"))
    return _result(lines >= 50, f"{lines} exemplos exportados")


def probe_data_playbook_etl() -> dict[str, Any]:
    path = DATA_PROJECT / "playbook.md"
    return _file_contains(path, "etl", "pipeline")


def probe_data_manifest() -> dict[str, Any]:
    path = DATA_PROJECT / "manifest.yaml"
    if not path.is_file():
        return _result(False, "manifest.yaml ausente")
    text = path.read_text(encoding="utf-8").lower()
    return _result("data" in text or "engineer" in text, "manifest OK")


# --- reliability-lead (R1–R5) ---


def probe_reliability_sprint_core() -> dict[str, Any]:
    return _run_pytest(SPRINT_RELIABILITY, timeout=180)


def probe_reliability_proof_gate() -> dict[str, Any]:
    try:
        from learning_agent.core import proofs

        suite = proofs.run_full_proof_suite()
        checks = suite.get("checks") or []
        names = {c.get("check") for c in checks}
        ok = suite.get("total", 0) >= 3 and "sqlite" in names
        return _result(ok, f"{len(checks)} checks, sqlite={'sqlite' in names}")
    except Exception as exc:
        return _result(False, str(exc)[:200])


def probe_reliability_ship_status() -> dict[str, Any]:
    try:
        from learning_agent.core import ship_pipeline

        status = ship_pipeline.build_ship_status()
        ok = "queue" in status and "velocity" in status
        return _result(ok, f"done={status.get('done_total', 0)}")
    except Exception as exc:
        return _result(False, str(exc)[:200])


def probe_reliability_playbook() -> dict[str, Any]:
    path = REL_PROJECT / "playbook.md"
    return _file_contains(path, "proof_gate", "debug")


def probe_reliability_operating_mode() -> dict[str, Any]:
    try:
        from learning_agent.core import ship_pipeline

        mode = ship_pipeline.load_operating_mode()
        focus = (mode.get("focus") or {}).get("primary_agent", "")
        ship = mode.get("ship") or {}
        ok = bool(focus) and ship.get("autonomous") is True
        return _result(ok, f"focus={focus} ship.autonomous={ship.get('autonomous')}")
    except Exception as exc:
        return _result(False, str(exc)[:200])


PROBE_REGISTRY: dict[str, Any] = {
    "frontend_sprint_core": probe_frontend_sprint_core,
    "frontend_progress_dashboard": probe_frontend_progress_dashboard,
    "frontend_distillation_panel": probe_frontend_distillation_panel,
    "frontend_external_exams_panel": probe_frontend_external_exams_panel,
    "frontend_component_doc": probe_frontend_component_doc,
    "qa_sprint_core": probe_qa_sprint_core,
    "qa_smoke_suite": probe_qa_smoke_suite,
    "qa_ci_workflow": probe_qa_ci_workflow,
    "qa_playbook_smoke": probe_qa_playbook_smoke,
    "qa_agents_registry": probe_qa_agents_registry,
    "data_sprint_core": probe_data_sprint_core,
    "data_sqlite_indexes": probe_data_sqlite_indexes,
    "data_hf_export": probe_data_hf_export,
    "data_playbook_etl": probe_data_playbook_etl,
    "data_manifest": probe_data_manifest,
    "reliability_sprint_core": probe_reliability_sprint_core,
    "reliability_proof_gate": probe_reliability_proof_gate,
    "reliability_ship_status": probe_reliability_ship_status,
    "reliability_playbook": probe_reliability_playbook,
    "reliability_operating_mode": probe_reliability_operating_mode,
}
