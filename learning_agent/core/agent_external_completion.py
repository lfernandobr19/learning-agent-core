"""Critérios externos de completude por agente."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import backend_probes, finance_probes, maintenance_probes

PROJECTS_DIR = PROJECT_ROOT / "agents" / "projects"

ALL_PROBES = {
    **finance_probes.PROBE_REGISTRY,
    **backend_probes.PROBE_REGISTRY,
    **maintenance_probes.PROBE_REGISTRY,
}

EXTERNAL_AGENTS = [
    "finance-lead",
    "backend-lead",
    "frontend-lead",
    "qa-guardian",
    "data-engineer",
    "reliability-lead",
]


def _criteria_path(agent: str) -> Path:
    return PROJECTS_DIR / agent / "completion-criteria.yaml"


def load_completion_criteria(agent: str) -> dict[str, Any] | None:
    path = _criteria_path(agent)
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["path"] = str(path.relative_to(PROJECT_ROOT))
    return data


def run_probe(probe_name: str) -> dict[str, Any]:
    fn = ALL_PROBES.get(probe_name)
    if fn is None:
        return {"passed": False, "detail": f"Probe desconhecido: {probe_name}"}
    try:
        return fn()
    except Exception as exc:
        return {"passed": False, "detail": f"Erro: {exc!r}"}


def assess_external_completion(agent: str) -> dict[str, Any]:
    cfg = load_completion_criteria(agent)
    if not cfg:
        return {
            "success": False,
            "agent": agent,
            "error": "completion-criteria.yaml não encontrado",
        }

    results: list[dict[str, Any]] = []
    passed_count = 0
    for item in cfg.get("criteria") or []:
        probe_name = item.get("probe", "")
        probe_result = run_probe(probe_name) if probe_name else {"passed": False, "detail": "sem probe"}
        passed = bool(probe_result.get("passed"))
        if passed:
            passed_count += 1
        results.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "description": item.get("description"),
                "ship_hint": item.get("ship_hint"),
                "probe": probe_name,
                "passed": passed,
                "detail": probe_result.get("detail", ""),
            }
        )

    total = int(cfg.get("total") or len(results))
    min_pass = int(cfg.get("min_pass") or total)
    external_ready = passed_count >= min_pass

    return {
        "success": True,
        "agent": agent,
        "display_name": cfg.get("display_name", agent),
        "min_pass": min_pass,
        "total": total,
        "passed_count": passed_count,
        "pass_rate_pct": round(100 * passed_count / max(total, 1), 1),
        "external_ready": external_ready,
        "criteria": results,
    }


def assess_all_with_external_criteria(agents: list[str] | None = None) -> dict[str, Any]:
    names = agents or EXTERNAL_AGENTS
    reports = [assess_external_completion(a) for a in names]
    return {
        "success": True,
        "agents": reports,
        "summary": {
            "assessed": len(reports),
            "external_ready": sum(1 for r in reports if r.get("external_ready")),
        },
    }
