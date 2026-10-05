"""Overnight IDE rebuild — treino L6 ravenna-ide (qualidade, journal completo)."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

IDE_AGENTS = [
    "frontend-lead",
    "backend-lead",
    "qa-guardian",
    "reliability-lead",
    "data-engineer",
]

PROJECT = "ravenna-ide-rebuild"
LOG = Path("data/ide_rebuild_overnight.log")
STATE = Path("data/ide_rebuild_overnight_state.json")
WORK_ORDERS = Path("data/ide_rebuild/work_orders")


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _parse_until(spec: str) -> datetime:
    now = datetime.now()
    parts = spec.strip().split(":")
    hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _save_work_order(agent: str, payload: dict) -> Path:
    WORK_ORDERS.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = WORK_ORDERS / f"{ts}-{agent}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_cycle(cycle_n: int, agent_idx: int) -> dict:
    from learning_agent.core import agent_action_journal, agent_autonomy, agent_ide_practice, ide_objectives

    agent = IDE_AGENTS[agent_idx % len(IDE_AGENTS)]
    log(f"=== Ciclo IDE #{cycle_n} agent={agent} (treino L6) ===")

    improvement = agent_ide_practice.run_ide_improvement_sprint(agent, broadcast_observer=False)
    topic = f"IDE rebuild — {agent}"
    journal_imp = agent_action_journal.complete_action_cycle(
        agent,
        "ide_improvement_sprint",
        topic,
        improvement,
        project=PROJECT,
    )
    log(f"ide_improvement journal_id={journal_imp.get('journal', {}).get('action_id')}")

    extra = None
    if agent == "qa-guardian":
        extra = agent_autonomy.execute_autonomy_action("proof_gate")
        agent_action_journal.complete_action_cycle(
            agent, "proof_gate", topic, extra, project=PROJECT
        )
    elif agent == "reliability-lead":
        extra = agent_autonomy.execute_autonomy_action("debug_sweep")
        agent_action_journal.complete_action_cycle(
            agent, "debug_sweep", topic, extra, project=PROJECT
        )

    collab = None
    completion = None
    if cycle_n % 4 == 0:
        collab = agent_autonomy.run_collab_dev_sprint(
            topic="Ravenna IDE treino L6 — paridade VS Code/Cursor",
            broadcast_observer=False,
        )
        agent_action_journal.complete_action_cycle(
            "ravenna",
            "collab_dev_sprint",
            topic,
            collab,
            project=PROJECT,
        )
        completion = ide_objectives.run_ide_completion_sprint()
        agent_action_journal.complete_action_cycle(
            agent,
            "ide_completion_sprint",
            topic,
            completion if isinstance(completion, dict) else {"success": True, "result": str(completion)},
            project=PROJECT,
        )

    report = ide_objectives.assess_completion()
    next_obj = report.get("next_objective") or {}

    work_order = {
        "cycle": cycle_n,
        "agent": agent,
        "project": PROJECT,
        "motor": "ravenna",
        "executor": "cursor",
        "quality_mode": True,
        "target": "ravenna-ide/",
        "next_objective": next_obj.get("id"),
        "next_title": next_obj.get("title"),
        "cursor_parity_pct": report.get("summary", {}).get("cursor_parity_pct"),
        "proposal": improvement.get("proposal", "")[:2000],
        "collab_plan": (collab or {}).get("plan", "")[:1500],
        "journal_required": True,
        "prompt_cursor": (
            f"@{agent} Treino L6 Dia IDE — milestone '{next_obj.get('id', 'layout')}' em ravenna-ide/. "
            "Registre cada ação e erro. proof_gate antes de encerrar."
        ),
    }
    wo_path = _save_work_order(agent, work_order)

    summary = {
        "cycle": cycle_n,
        "agent": agent,
        "project": PROJECT,
        "cursor_parity_pct": report.get("summary", {}).get("cursor_parity_pct"),
        "next_objective": next_obj.get("id"),
        "work_order": str(wo_path),
        "journal_action_id": journal_imp.get("journal", {}).get("action_id"),
    }
    Path("data/ide_rebuild_overnight_last.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"resumo: {json.dumps(summary, ensure_ascii=False)}")
    return summary


def main() -> int:
    from learning_agent.core import ship_pipeline

    paused, reason = ship_pipeline.is_overnight_paused("ide_rebuild")
    if paused:
        log(reason)
        print(reason)
        return 0

    parser = argparse.ArgumentParser(description="Overnight IDE rebuild — treino L6")
    parser.add_argument("--until", default="06:00")
    parser.add_argument("--interval", type=int, default=1800)
    args = parser.parse_args()

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("RAG_DISABLE_CHROMA", "true")
    os.environ.setdefault("AUTO_PROOFS", "false")

    end_at = _parse_until(args.until)
    log(f"IDE treino L6 até {end_at.isoformat(timespec='minutes')} — journal em toda ação")

    state = {}
    if STATE.is_file():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    cycle = int(state.get("cycle", 0))
    agent_idx = int(state.get("agent_idx", 0))

    while datetime.now() < end_at:
        cycle += 1
        try:
            run_cycle(cycle, agent_idx)
            agent_idx += 1
            STATE.write_text(
                json.dumps({"cycle": cycle, "agent_idx": agent_idx}, indent=2),
                encoding="utf-8",
            )
        except KeyboardInterrupt:
            log("Interrompido")
            return 0
        except Exception as exc:
            log(f"erro: {exc!r}")
            try:
                from learning_agent.core import agent_action_journal

                agent_action_journal.log_action(
                    "ravenna",
                    "ide_rebuild_cycle",
                    topic=f"ciclo {cycle}",
                    project=PROJECT,
                    success=False,
                    error=str(exc)[:800],
                )
            except Exception:
                pass

        remaining = (end_at - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        sleep_s = min(args.interval, int(remaining))
        log(f"Próximo ciclo IDE em {sleep_s}s")
        time.sleep(max(120, sleep_s))

    log(f"IDE overnight encerrado — {cycle} ciclos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
