"""Refinamento L6 exigente — Cursor mentor + benchmark strict."""

from __future__ import annotations

import argparse
import json
import sys

from learning_agent.core import l6_refinement


def main() -> int:
    parser = argparse.ArgumentParser(description="Refinamento L6 dos agentes core")
    parser.add_argument("--agent", default="", help="Um agente ou vazio = todos")
    parser.add_argument("--rounds", type=int, default=2, help="Rodadas de refinamento")
    args = parser.parse_args()

    if args.agent:
        result = l6_refinement.refine_agent_to_l6(
            args.agent, max_rounds=args.rounds, broadcast_observer=False
        )
    else:
        result = l6_refinement.refine_all_core_agents(
            max_rounds=args.rounds, broadcast_observer=False
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.agent:
        ok = bool(result.get("parity_met"))
    else:
        ok = result.get("parity_met", 0) == result.get("total", 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
