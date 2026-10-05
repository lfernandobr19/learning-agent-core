"""Relatório de evolução por agente — níveis 1–5 com critérios de Especialista."""

from __future__ import annotations

import json
import sys

from learning_agent.core import agent_capability, progress


def build_report() -> dict:
    report = agent_capability.assess_ecosystem()
    prog = progress.get_progress()
    report["ecosystem"] = {
        **report.get("ecosystem", {}),
        "total_notes": prog.get("summary", {}).get("total_notes", 0),
        "total_quizzes": prog.get("summary", {}).get("total_quizzes", 0),
        "weak_areas": prog.get("weak_areas", [])[:6],
    }
    return report


def main() -> None:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
