"""Exame mensal — rubrica externa por agente."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_benchmarks, agent_external_completion

EXAMS_DIR = PROJECT_ROOT / "agents" / "exams"
MONTHLY_DIR = EXAMS_DIR / "monthly"
RESULTS_PATH = PROJECT_ROOT / "data" / "monthly_exam_results.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def list_monthly_exams(agent: str) -> list[Path]:
    if not MONTHLY_DIR.is_dir():
        return []
    return sorted(MONTHLY_DIR.glob(f"{agent}_*.yaml"))


def load_monthly_exam(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def run_monthly_exam(agent: str, exam_id: str | None = None) -> dict[str, Any]:
    """Executa exame mensal — combina critérios externos + blinds do exame."""
    paths = list_monthly_exams(agent)
    if not paths:
        return {"success": False, "error": f"Nenhum exame mensal em {MONTHLY_DIR}"}

    path = paths[-1]
    if exam_id:
        match = [p for p in paths if exam_id in p.name]
        if match:
            path = match[0]

    cfg = load_monthly_exam(path)
    external = agent_external_completion.assess_external_completion(agent)

    blind_results: list[dict[str, Any]] = []
    for blind_id in cfg.get("blind_ids") or ["blind_01"]:
        r = agent_benchmarks.run_blind(agent, blind_id)
        if r.get("success"):
            agent_benchmarks.save_blind_result(r)
        blind_results.append(r)

    blind_avg = round(
        sum(r.get("composite", 0) for r in blind_results) / max(len(blind_results), 1),
        1,
    )
    pass_threshold = float(cfg.get("pass_threshold") or 70)
    external_ok = bool(external.get("external_ready"))
    blind_ok = blind_avg >= pass_threshold
    passed = external_ok and blind_ok

    result = {
        "success": True,
        "agent": agent,
        "exam_file": str(path.relative_to(PROJECT_ROOT)),
        "title": cfg.get("title", ""),
        "recorded_at": _utcnow(),
        "external": external,
        "blind_results": blind_results,
        "blind_avg": blind_avg,
        "pass_threshold": pass_threshold,
        "passed": passed,
        "verdict": "GO" if passed else "NO-GO",
    }

    history = {"runs": []}
    if RESULTS_PATH.is_file():
        try:
            history = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    history.setdefault("runs", []).append(result)
    history["runs"] = history["runs"][-24:]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
