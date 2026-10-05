"""CLI — ciclo de decisão paper finance-lead."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    from learning_agent.core.cli_encoding import ensure_utf8_stdio

    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Finance-lead paper decision loop")
    parser.add_argument("--dry-run", action="store_true", help="Gera decisão sem pending/Telegram")
    parser.add_argument("--approve", metavar="ID", help="Aprovar decisão pendente")
    parser.add_argument("--register", metavar="ID", help="Registrar no journal sem portfolio")
    parser.add_argument("--list", action="store_true", help="Listar pendentes")
    args = parser.parse_args()

    from learning_agent.core import finance_decision_loop as fdl

    if args.list:
        print(json.dumps(fdl.list_pending_decisions(), ensure_ascii=False, indent=2))
        return 0
    if args.approve:
        print(json.dumps(fdl.approve_decision(args.approve, mode="approve"), ensure_ascii=False, indent=2))
        return 0
    if args.register:
        print(json.dumps(fdl.approve_decision(args.register, mode="register"), ensure_ascii=False, indent=2))
        return 0
    if args.dry_run:
        market = fdl.load_market_context()
        news = fdl.load_news_context()
        decision = fdl.generate_l6_decision(market, news)
        validation = fdl.validate_decision_probes(decision)
        print(json.dumps({"decision": decision, "validation": validation}, ensure_ascii=False, indent=2))
        return 0

    result = fdl.run_decision_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
