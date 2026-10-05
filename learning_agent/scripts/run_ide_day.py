"""CLI — treino IDE L6 (kickoff, status, fechamento diário)."""

from __future__ import annotations

import argparse
import json
import sys

from learning_agent.core.cli_encoding import ensure_utf8_stdio
from learning_agent.core import ide_rebuild_day


def main() -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Treino IDE Ravenna — motor + agentes")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_kick = sub.add_parser("kickoff", help="Inicia dia (default: dia 1)")
    p_kick.add_argument("--day", type=int, default=1)

    sub.add_parser("status", help="Estado do treino + aceite do dia")

    p_close = sub.add_parser("close", help="Fecha dia — closure, lição, quiz")
    p_close.add_argument("--day", type=int, default=None)
    p_close.add_argument("--no-advance", action="store_true")

    p_prompt = sub.add_parser("prompt", help="Imprime prompt Cursor do dia atual")
    p_prompt.add_argument("--day", type=int, default=None)

    args = parser.parse_args()

    if args.cmd == "kickoff":
        result = ide_rebuild_day.kickoff(day=args.day)
    elif args.cmd == "status":
        result = ide_rebuild_day.status()
    elif args.cmd == "close":
        result = ide_rebuild_day.close_day(day=args.day, advance=not args.no_advance)
    elif args.cmd == "prompt":
        day = args.day
        if day is None:
            day = int(ide_rebuild_day.load_state().get("current_day") or 1)
        plan = ide_rebuild_day.get_day_plan(day)
        result = {"success": True, "prompt": ide_rebuild_day.build_cursor_prompt(plan)}
    else:
        result = {"success": False, "error": "comando inválido"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.cmd == "prompt" and result.get("prompt"):
        print("\n--- CURSOR ---\n")
        print(result["prompt"])

    return 0 if result.get("success") is not False else 1


if __name__ == "__main__":
    sys.exit(main())
