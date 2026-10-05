"""Exame mensal — finance-lead (ou outro agente com critérios externos)."""

from __future__ import annotations

import argparse
import json

from learning_agent.core import agent_monthly_exams


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="finance-lead")
    parser.add_argument("--exam-id", default="", help="Substring do YAML mensal")
    args = parser.parse_args()

    result = agent_monthly_exams.run_monthly_exam(
        args.agent.strip(),
        exam_id=args.exam_id.strip() or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
