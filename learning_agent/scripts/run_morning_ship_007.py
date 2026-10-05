"""Encerramento do sprint — blind_02 + SHIP-007 (antes do PC desligar ~06:00)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from learning_agent.config import PROJECT_ROOT

LOG = PROJECT_ROOT / "data" / "scheduled" / "morning-ship-007.log"


def _log(msg: str) -> None:
    import time

    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run_morning_ship_007(*, skip_ship: bool = False) -> dict:
    from learning_agent.core import agent_benchmarks, ship_autonomous, telegram_alerts

    _log("=== morning ship-007 inicio ===")

    blind = agent_benchmarks.run_blind("finance-lead", "blind_02")
    if blind.get("success"):
        agent_benchmarks.save_blind_result(blind)
    passed = bool(blind.get("passed"))
    score = blind.get("composite", blind.get("score", 0))
    _log(f"blind_02: passed={passed} score={score}")

    ship_result: dict = {"skipped": True}
    if not skip_ship:
        from learning_agent.core import ship_pipeline

        item = next((q for q in ship_pipeline.list_queue() if q.get("id") == "SHIP-007"), None)
        if item:
            ship_result = ship_autonomous.process_item(item)
            _log(f"SHIP-007: success={ship_result.get('success')} stage={ship_result.get('stage', 'ok')}")
        else:
            _log("SHIP-007: ja processado ou ausente da fila")
            ship_result = {"success": True, "note": "not in queue"}

    summary = {
        "success": blind.get("success") and ship_result.get("success", False),
        "blind_02": {"passed": passed, "score": score, "detail": blind},
        "ship_007": ship_result,
    }

    try:
        emoji = "OK" if passed and ship_result.get("success") else "FALHOU"
        telegram_alerts.send_alert(
            f"Sprint finance-lead (06h)\n"
            f"blind_02: {score}% {'PASS' if passed else 'FAIL'}\n"
            f"SHIP-007: {emoji}\n"
            f"Pode desligar o PC."
        )
    except Exception as exc:
        _log(f"telegram alert: {exc!r}")

    out = PROJECT_ROOT / "data" / "scheduled" / "morning-ship-007-last.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _log("=== morning ship-007 fim ===")
    return summary


def main() -> int:
    skip = "--skip-ship" in sys.argv
    summary = run_morning_ship_007(skip_ship=skip)
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
