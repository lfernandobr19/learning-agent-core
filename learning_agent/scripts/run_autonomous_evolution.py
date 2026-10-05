"""Evolução autônoma — metodologia de estudo estruturada por agente.

Cada ciclo (~30 min):
  1. Sessão de estudo completa para UM agente (prioridade L6 fraco)
  2. Manutenção leve: export HF; index RAG a cada N ciclos; brain a cada N pares

Não destila em massa a cada ciclo — destilação só após sessão de estudo (qualidade).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

LOG = Path("data/autonomous_evolution.log")
STATE = Path("data/autonomous_evolution_state.json")


def _evolution_subprocess() -> bool:
    return os.environ.get("RAG_DISABLE_CHROMA", "").lower() in {"1", "true", "yes", "on"}


def _cached_readiness() -> dict:
    from learning_agent.config import RAVEN_READINESS_STATE_PATH

    if RAVEN_READINESS_STATE_PATH.is_file():
        try:
            data = json.loads(RAVEN_READINESS_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "summary" in data:
                return data
        except json.JSONDecodeError:
            pass
    return {"summary": {"readiness_pct": 0.0}}


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _load_state() -> dict:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"pairs_at_last_brain": 0, "cycles": 0}


def _save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_cycle(
    *,
    index_every: int = 3,
    brain_every_n_pairs: int = 5,
    collab_every: int = 8,
    maintenance: bool = False,
) -> dict:
    from learning_agent import db
    from learning_agent.config import L6_REFINEMENT_EVERY_N_CYCLES
    from learning_agent.core import (
        agent_study_methodology,
        codebase,
        finetune,
        l6_refinement,
        raven_readiness,
        software_excellence,
    )

    state = _load_state()
    state["cycles"] = int(state.get("cycles", 0)) + 1
    cycle_n = state["cycles"]
    log(f"=== Ciclo estudo #{cycle_n}{' (manutenção)' if maintenance else ''} ===")

    db.init_db()
    with db.get_connection() as c:
        pairs_before = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]

    # Núcleo: uma sessão pedagógica completa (1 agente)
    study = agent_study_methodology.run_ecosystem_study_round(
        maintenance=maintenance,
        broadcast_observer=False,
        full_verify=False,  # L6 strict só no batch L6_REFINEMENT_EVERY_N_CYCLES
    )
    log(
        f"estudo: {study.get('agent')} dim={study.get('dimension')} "
        f"distilled={study.get('distilled')}"
    )

    # Index RAG — caro; não todo ciclo
    if cycle_n % max(1, index_every) == 0:
        if os.environ.get("RAG_DISABLE_CHROMA", "").lower() in {"1", "true", "yes", "on"}:
            log("index_codebase: omitido (RAG_DISABLE_CHROMA — API mantém Chroma)")
        else:
            try:
                idx = codebase.index_codebase(["learning_agent", "ravenna-ide"])
                log(f"index_codebase: {idx.get('indexed_files', idx)} arquivos")
            except Exception as exc:
                log(f"index_codebase falhou: {exc!r}")

    # Sprint colaborativo — pesado (Ollama multi-agente); só fora do subprocess evolution
    collab = None
    if cycle_n % max(1, collab_every) == 0 and not _evolution_subprocess():
        try:
            from learning_agent.core import agent_autonomy

            collab = agent_autonomy.run_collab_dev_sprint(broadcast_observer=False)
            log(f"collab_sprint: {collab.get('topic', '')[:60]}")
        except Exception as exc:
            log(f"collab_sprint falhou: {exc!r}")
    elif cycle_n % max(1, collab_every) == 0:
        log("collab_sprint: omitido no evolution subprocess (use API /api/agents/collab)")

    with db.get_connection() as c:
        pairs_after = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]

    export = finetune.export_training_data(min_pairs=0)
    hf = finetune.export_hf_sft_dataset()

    brain = None
    last_brain = int(state.get("pairs_at_last_brain", 0))
    if pairs_after - last_brain >= brain_every_n_pairs:
        if _evolution_subprocess():
            log("brain: omitido no subprocess evolution (rode brain via API)")
        else:
            try:
                brain = software_excellence.run_brain_pipeline(
                    dry_run=False, broadcast_observer=False
                )
                state["pairs_at_last_brain"] = pairs_after
                log(f"brain: {brain.get('model', {}).get('few_shot_count')} few-shots")
            except Exception as exc:
                log(f"brain falhou: {exc!r}")

    l6_result = None
    if cycle_n % max(1, L6_REFINEMENT_EVERY_N_CYCLES) == 0:
        try:
            l6_result = l6_refinement.refine_all_core_agents(
                max_rounds=1, broadcast_observer=False
            )
            log(f"L6 batch: {l6_result.get('parity_met')}/{l6_result.get('total')}")
        except Exception as exc:
            log(f"L6 batch falhou: {exc!r}")

    if _evolution_subprocess():
        readiness = _cached_readiness()
    else:
        readiness = raven_readiness.assess_readiness()
    summary = {
        "cycle": cycle_n,
        "methodology": "structured_study",
        "study_agent": study.get("agent"),
        "study_dimension": study.get("dimension"),
        "pairs_before": pairs_before,
        "pairs_after": pairs_after,
        "training_examples": export["examples"],
        "readiness_pct": readiness["summary"]["readiness_pct"],
        "brain_refreshed": brain is not None,
        "hf_dataset": hf.get("path"),
        "collab_sprint": collab.get("topic") if collab else None,
        "l6_refinement": (
            {"parity_met": l6_result.get("parity_met"), "total": l6_result.get("total")}
            if l6_result
            else None
        ),
    }
    _save_state(state)
    Path("data/autonomous_evolution_last.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"resumo: {json.dumps(summary, ensure_ascii=False)}")
    return summary


def main() -> int:
    from learning_agent.core import ship_pipeline

    parser = argparse.ArgumentParser(description="Evolução autônoma — estudo estruturado")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--maintenance", action="store_true", help="Só agentes de manutenção; não pausa finance overnight")
    parser.add_argument("--interval", type=int, default=1800, help="Segundos entre ciclos (default 30min)")
    args = parser.parse_args()

    if not args.maintenance:
        paused, reason = ship_pipeline.is_overnight_paused("core_evolution")
        if paused:
            log(reason)
            print(reason, file=sys.stderr)
            return 0

    os.environ.setdefault("STUDENT_MODEL", "phi3:mini")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    # Evolution loop usa Ollama — não carregar Chroma no mesmo processo (Windows crash)
    os.environ.setdefault("RAG_DISABLE_CHROMA", "true")
    os.environ.setdefault("EVOLUTION_SKIP_DISTILL", "true")
    # Prática hands-on obrigatória — não usar light por default (pula practice/verify)
    os.environ.setdefault("EVOLUTION_LIGHT_STUDY", "false")
    os.environ.setdefault("AUTO_PROOFS", "true")

    if args.maintenance:
        log("Modo manutenção — backend/frontend/QA/data/reliability (finance-lead intacto)")

    if args.loop:
        log("Modo estudo estruturado — Ctrl+C para parar (1 subprocesso/ciclo)")
        cycle_script = str(Path(__file__).resolve())
        while True:
            try:
                import subprocess

                env = {**os.environ}
                env.setdefault("STUDENT_MODEL", "phi3:mini")
                env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
                env.setdefault("RAG_DISABLE_CHROMA", "true")
                env.setdefault("EVOLUTION_SKIP_DISTILL", "true")
                env.setdefault("EVOLUTION_LIGHT_STUDY", "false")
                env.setdefault("AUTO_PROOFS", "true")
                cmd = [sys.executable, cycle_script]
                if args.maintenance:
                    cmd.append("--maintenance")
                r = subprocess.run(
                    cmd,
                    cwd=str(Path.cwd()),
                    env=env,
                )
                if r.returncode not in (0, None):
                    log(f"ciclo subprocess exit={r.returncode} — retomando após intervalo")
            except KeyboardInterrupt:
                log("Interrompido")
                return 0
            except Exception as exc:
                log(f"erro: {exc!r}")
            time.sleep(max(120, args.interval))
    else:
        run_cycle(maintenance=args.maintenance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
