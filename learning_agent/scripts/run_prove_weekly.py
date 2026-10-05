"""Prove semanal — critérios externos + benchmarks cegos + curadoria."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from learning_agent.core import agent_benchmarks, agent_external_completion, ship_pipeline

REPORT = Path("data/prove_weekly_last.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ciclo Prove semanal")
    parser.add_argument("--agent", default="finance-lead")
    parser.add_argument("--curate", action="store_true", help="Rodar curadoria de destilação")
    parser.add_argument("--generate-blind", action="store_true", help="Gerar novo benchmark cego antes do prove")
    args = parser.parse_args()

    os.environ.setdefault("RAG_DISABLE_CHROMA", "true")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    agent = args.agent.strip()

    blind_generated = None
    if args.generate_blind:
        from learning_agent.scripts import generate_blind_benchmark

        blind_generated = generate_blind_benchmark.generate_blind(agent)

    external = agent_external_completion.assess_external_completion(agent)

    blinds = agent_benchmarks.list_blinds(agent)
    blind_runs = []
    for b in blinds:
        blind_id = b.get("id") or b.get("_file", "").replace(".yaml", "")
        r = agent_benchmarks.run_blind(agent, blind_id)
        if r.get("success"):
            agent_benchmarks.save_blind_result(r)
        blind_runs.append(r)

    curation = None
    if args.curate:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "curate_distillation",
            Path(__file__).resolve().parent / "curate_distillation.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(mod)
        curation = mod.curate(dry_run=False)

    ship = ship_pipeline.build_ship_status()
    report = {
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "agent": agent,
        "blind_generated": blind_generated,
        "external": external,
        "blind_runs": blind_runs,
        "ship_velocity": ship.get("velocity"),
        "curation": curation,
        "alert_train_without_ship": ship.get("velocity", {}).get("alert", False),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    try:
        from learning_agent.core import telegram_alerts

        telegram_alerts.alert_prove_report(report)
    except Exception:
        pass

    return 0 if external.get("external_ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
