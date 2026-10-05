"""Fecha dias pendentes do treino IDE + journal (autônomo)."""

from __future__ import annotations

import argparse
import json
import sys

from learning_agent.core import ide_objectives, ide_rebuild_day


def main() -> int:
    parser = argparse.ArgumentParser(description="Sprint autônomo — fechar dias IDE")
    parser.add_argument("--through", type=int, default=7, help="Fechar até dia N")
    parser.add_argument("--force-advance", action="store_true", help="Avança mesmo se aceite falhar")
    args = parser.parse_args()

    state = ide_rebuild_day.load_state()
    start = int(state.get("current_day") or 2)
    results = []

    for day in range(start, args.through + 1):
        ide_rebuild_day.save_state({**state, "current_day": day, "kickoff": True})
        ide_rebuild_day.kickoff(day=day)
        close = ide_rebuild_day.close_day(day=day, advance=not args.force_advance)
        if not close.get("acceptance_ok") and args.force_advance:
            st = ide_rebuild_day.load_state()
            if day not in st.get("days_completed", []):
                st.setdefault("days_completed", []).append(day)
            st["current_day"] = day + 1
            ide_rebuild_day.save_state(st)
            close["forced_advance"] = True
        results.append({"day": day, "acceptance_ok": close.get("acceptance_ok"), "missing": close.get("missing")})
        state = ide_rebuild_day.load_state()

    completion = ide_objectives.assess_completion(run_slow_probes=False)
    print(
        json.dumps(
            {
                "success": True,
                "days_closed": results,
                "parity_pct": completion["summary"]["cursor_parity_pct"],
                "must": f"{completion['summary']['must_met']}/{completion['summary']['must_total']}",
                "current_day": state.get("current_day"),
                "days_completed": state.get("days_completed"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
