"""Fase 1 — consolidar reasoning, quiz, proof gate e lacunas (finance-lead)."""

from __future__ import annotations

import os
from typing import Any

AGENT = "finance-lead"
_SPACED_MAX = int(os.environ.get("FINANCE_SPACED_REVIEW_MAX", "8"))
_REMEDIATION_MAX = int(os.environ.get("FINANCE_QUIZ_REMEDIATION_MAX", "8"))


def run_phase1_consolidation(*, full: bool = False) -> dict[str, Any]:
    """Sprint curto: SM-2, drill, remediação quiz, proof gate; parity se full=True."""
    from learning_agent.core import (
        agent_collaboration,
        agent_learning_loop,
        agent_model_parity,
        agent_spaced_review,
        finance_quiz_boost,
    )

    phases: dict[str, Any] = {}
    phases["spaced_review"] = agent_spaced_review.run_spaced_review(
        AGENT, max_items=_SPACED_MAX, broadcast_observer=False
    )
    phases["quiz_remediation"] = finance_quiz_boost.run_quiz_remediation(
        max_items=_REMEDIATION_MAX
    )
    phases["weak_area_drill"] = agent_learning_loop.run_weak_area_drill(
        AGENT, broadcast_observer=False
    )
    phases["proof_gate"] = agent_learning_loop.run_proof_gate(broadcast_observer=False)
    phases["research_gaps"] = agent_collaboration.agent_research_gaps(AGENT, max_topics=2)

    if full:
        try:
            phases["parity"] = agent_model_parity.run_strict_parity_assessment(
                AGENT, broadcast_observer=False
            )
        except Exception as exc:
            phases["parity"] = {"success": False, "error": str(exc)[:200]}

    proof_ok = bool((phases.get("proof_gate") or {}).get("all_passed"))
    reviewed = len((phases.get("spaced_review") or {}).get("reviewed") or [])
    remediation = phases.get("quiz_remediation") or {}
    return {
        "success": True,
        "action": "finance_phase1_consolidation",
        "agent": AGENT,
        "proof_gate_ok": proof_ok,
        "quiz_items_reviewed": reviewed + int(remediation.get("total") or 0),
        "quiz_remediation_correct": remediation.get("correct"),
        "phases": phases,
    }
