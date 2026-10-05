"""Refinamento L6 — mentor Cursor, estudo entre pares, re-avaliação exigente."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR, MODEL_PARITY_STRICT_MIN_SCORE
from learning_agent.core import agent_autonomy, agent_model_parity, cursor_mentor
from learning_agent.core.agent_capability import CORE_AGENTS

STATE_PATH = DATA_DIR / "l6_refinement_state.json"


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"rounds": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _weakest_dimension(assessment: dict[str, Any]) -> str:
    dims = assessment.get("dimensions", {})
    if not dims:
        return "decision"
    return min(dims.keys(), key=lambda k: float(dims[k].get("score", 0)))


def refine_agent_to_l6(
    agent: str,
    *,
    max_rounds: int = 2,
    broadcast_observer: bool = False,
) -> dict[str, Any]:
    """Ciclo: avalia strict → mentor Cursor → par → sprint → re-avalia."""
    slug = agent.strip().lower().replace("_", "-")
    state = _load_state()
    rounds_log: list[dict[str, Any]] = []

    assessment = agent_model_parity.run_strict_parity_assessment(
        slug, broadcast_observer=broadcast_observer
    )
    if assessment.get("parity_met"):
        return {
            "success": True,
            "agent": slug,
            "parity_met": True,
            "rounds": 0,
            "final": assessment,
        }

    for round_n in range(1, max_rounds + 1):
        weak = _weakest_dimension(assessment)
        steps: dict[str, Any] = {"round": round_n, "weak_dimension": weak}

        steps["mentor"] = cursor_mentor.run_cursor_mentor_session(slug, weak, sync_cloud=False)

        try:
            steps["peer_study"] = cursor_mentor.run_peer_study_round(slug)
        except Exception as exc:
            steps["peer_study"] = {"success": False, "error": str(exc)[:200]}

        if weak == "decision":
            try:
                steps["micro_sprint"] = agent_autonomy.execute_autonomy_action(
                    "execute_micro_sprint",
                    topic=f"L6 {slug}: decisão com critérios de aceite e provas",
                )
            except Exception as exc:
                steps["micro_sprint"] = {"success": False, "error": str(exc)[:200]}
        else:
            try:
                steps["proof_gate"] = agent_autonomy.execute_autonomy_action("proof_gate")
            except Exception as exc:
                steps["proof_gate"] = {"success": False, "error": str(exc)[:200]}

        assessment = agent_model_parity.run_strict_parity_assessment(
            slug, broadcast_observer=broadcast_observer
        )
        steps["assessment"] = {
            "composite": assessment.get("composite_score"),
            "parity_met": assessment.get("parity_met"),
            "dimensions": {
                k: v.get("score") for k, v in assessment.get("dimensions", {}).items()
            },
        }
        rounds_log.append(steps)

        if assessment.get("parity_met"):
            break

    state["rounds"][slug] = state.get("rounds", {}).get(slug, 0) + len(rounds_log)
    _save_state(state)

    return {
        "success": True,
        "action": "refine_agent_to_l6",
        "agent": slug,
        "parity_met": assessment.get("parity_met", False),
        "composite_score": assessment.get("composite_score"),
        "min_score": MODEL_PARITY_STRICT_MIN_SCORE,
        "rounds_executed": len(rounds_log),
        "rounds_log": rounds_log,
        "final": assessment,
    }


def refine_all_core_agents(
    *,
    max_rounds: int = 2,
    broadcast_observer: bool = False,
    only_below_min: bool = True,
) -> dict[str, Any]:
    """Refina core agents; por padrão só os abaixo do L6 strict (evita regressão)."""
    parity_state = agent_model_parity._load_state().get("agents", {})
    results: list[dict[str, Any]] = []
    for slug in CORE_AGENTS:
        cached = parity_state.get(slug, {})
        if only_below_min and cached.get("parity_met"):
            results.append(
                {
                    "success": True,
                    "agent": slug,
                    "parity_met": True,
                    "skipped": True,
                    "composite_score": cached.get("composite_score"),
                    "note": "já L6 — não re-avaliar no batch",
                }
            )
            continue
        try:
            row = refine_agent_to_l6(
                slug,
                max_rounds=max_rounds,
                broadcast_observer=broadcast_observer,
            )
            results.append(row)
        except Exception as exc:
            results.append({"success": False, "agent": slug, "error": str(exc)[:200]})

    met = sum(1 for r in results if r.get("parity_met"))
    summary = {
        "success": True,
        "action": "refine_all_core_agents",
        "total": len(CORE_AGENTS),
        "parity_met": met,
        "min_score": MODEL_PARITY_STRICT_MIN_SCORE,
        "agents": results,
    }
    Path(DATA_DIR / "l6_refinement_last.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
