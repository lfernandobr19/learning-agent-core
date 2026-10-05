"""Sessão noturna — evolução focada no finance-lead (investimento PF).

Diferente do evolution loop genérico:
  - Agente fixo: finance-lead
  - Destilação ATIVA (sem EVOLUTION_SKIP_DISTILL / LIGHT)
  - Rotação knowledge → reasoning → decision
  - Teacher Groq em tópicos do overnight-prompts.yaml
  - Export HF a cada ciclo; brain_pipeline a cada +5 pares (se Ollama local ok)

Uso:
  python -m learning_agent.scripts.run_finance_lead_overnight --until 06:00
  python -m learning_agent.scripts.run_finance_lead_overnight --hours 8 --interval 900
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

AGENT = "finance-lead"
PROJECT = "finance-lead-mastery"
LOG = Path("data/finance_lead_overnight.log")
STATE = Path("data/finance_lead_overnight_state.json")
PROMPTS = Path("agents/projects/finance-lead/overnight-prompts.yaml")
DIMENSIONS = ("knowledge", "reasoning", "decision")


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _load_prompts() -> dict[str, Any]:
    if not PROMPTS.is_file():
        return {"teacher_topics": []}
    return yaml.safe_load(PROMPTS.read_text(encoding="utf-8")) or {}


def _load_state() -> dict[str, Any]:
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"cycle": 0, "topic_index": 0, "dim_index": 0, "pairs_at_last_brain": 0}


def _save_state(state: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_until(spec: str) -> datetime:
    """HH:MM local, ou data ISO: 2026-06-11T05:30 / 11/06/2026 05:30."""
    spec = spec.strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d/%m/%Y-%H:%M"):
        try:
            target = datetime.strptime(spec, fmt)
            if target <= datetime.now():
                raise ValueError(f"Horario no passado: {spec}")
            return target
        except ValueError as exc:
            if "no passado" in str(exc):
                raise
            continue
    now = datetime.now()
    parts = spec.strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _check_vast_tunnel() -> bool:
    from learning_agent.core import overnight_runtime

    return overnight_runtime.vast_tunnel_available()


def _reasoning_score(agent: str = AGENT) -> float | None:
    from learning_agent.core import agent_capability

    cap = agent_capability.compute_agent_capability(agent)
    dim = (cap.get("level_6") or {}).get("dimensions", {}).get("reasoning", {})
    score = dim.get("score")
    return float(score) if score is not None else None


def _configure_cycle_runtime(cycle_n: int) -> dict[str, str]:
    from learning_agent.core import overnight_runtime

    profile = overnight_runtime.configure_for_cycle(cycle_n=cycle_n)
    log(
        f"runtime profile={profile.get('profile')} "
        f"student={profile.get('chat_model')} base={profile.get('chat_api_base')}"
    )
    return profile


def _distill_teacher_topic(topic: str, tags: list[str]) -> dict[str, Any] | None:
    from learning_agent.core import distillation

    if not distillation.is_configured():
        log("teacher distill: distillation não configurada")
        return None
    try:
        return distillation.distill_topic(
            topic,
            tags=["finance", "investimento", "overnight", *tags],
            sync_cloud=False,
        )
    except Exception as exc:
        log(f"teacher distill falhou: {exc!r}")
        return None


def _maybe_brain(pairs_after: int, state: dict[str, Any], every: int = 5) -> bool:
    last = int(state.get("pairs_at_last_brain", 0))
    if pairs_after - last < every:
        return False
    try:
        from learning_agent.core import software_excellence

        result = software_excellence.run_brain_pipeline(dry_run=False, broadcast_observer=False)
        state["pairs_at_last_brain"] = pairs_after
        log(f"brain_pipeline: {result.get('model', {}).get('target_model', 'raven')}")
        return True
    except Exception as exc:
        log(f"brain_pipeline omitido (Ollama local?): {exc!r}")
        return False


def _ship_train_topic() -> str | None:
    try:
        from learning_agent.core import ship_pipeline

        item = ship_pipeline.get_next_ready_item()
        if item:
            return str(item.get("train_topic") or item.get("title") or "")
    except Exception:
        pass
    return None


def _pick_dimension(state: dict[str, Any], cfg: dict[str, Any], *, focus: str = "") -> str:
    if state.get("force_reasoning_remediation"):
        return "reasoning"
    focus_key = focus or os.environ.get("FINANCE_OVERNIGHT_FOCUS", "")
    if focus_key == "l6-operational":
        pattern = (cfg.get("l6_operational_focus") or {}).get("dimension_pattern") or [
            "reasoning",
            "knowledge",
            "reasoning",
            "knowledge",
            "decision",
        ]
        cycle_n = int(state.get("cycle", 0))
        return pattern[(cycle_n - 1) % len(pattern)]
    dim_idx = int(state.get("dim_index", 0)) % len(DIMENSIONS)
    return DIMENSIONS[dim_idx]


def _pick_teacher_topics(cfg: dict[str, Any], *, focus: str = "") -> list[dict[str, Any]]:
    focus_key = focus or os.environ.get("FINANCE_OVERNIGHT_FOCUS", "")
    if focus_key == "l6-operational":
        extra = (cfg.get("l6_operational_focus") or {}).get("teacher_topics") or []
        base = cfg.get("teacher_topics") or []
        return [*extra, *base]
    return cfg.get("teacher_topics") or []


def _run_l6_operational_sprint(cycle_n: int) -> dict[str, Any] | None:
    """Consolidação + blind benchmarks em ciclos focados L6 operacional."""
    from learning_agent.core import agent_benchmarks, finance_consolidation

    out: dict[str, Any] = {}
    out["consolidation"] = finance_consolidation.run_phase1_consolidation(
        full=cycle_n % 4 == 1
    )
    log(
        f"L6 sprint: proof_gate={out['consolidation'].get('proof_gate_ok')} "
        f"quiz={out['consolidation'].get('quiz_items_reviewed')} "
        f"rem_ok={out['consolidation'].get('quiz_remediation_correct')}"
    )

    batch_every = int(os.environ.get("FINANCE_BLIND_BATCH_EVERY_CYCLES", "10"))
    fresh_every = int(os.environ.get("FINANCE_BLIND_FRESH_EVERY_CYCLES", "4"))

    if cycle_n % batch_every == 0:
        from learning_agent.scripts.run_finance_blind_exams import (
            notify_blind_report,
            run_batch,
        )

        log(f"Blind Opção B: batch 5x (ciclo #{cycle_n}, every={batch_every})")
        blind_report = run_batch(repeats=5)
        notify_blind_report(blind_report, source="overnight-batch")
        out["blind_automation"] = {"mode": "batch", "report": blind_report}
        for b in blind_report.get("blinds") or []:
            log(
                f"  {b.get('blind_id')}: mean={b.get('mean_composite')}% "
                f"pass={b.get('pass_count')}/{b.get('attempts')}"
            )
    elif cycle_n % fresh_every == 0:
        from learning_agent.scripts.run_finance_blind_exams import (
            notify_blind_report,
            run_fresh_blinds,
        )

        log(f"Blind Opção C: fresh 1x/blind (ciclo #{cycle_n}, every={fresh_every})")
        blind_report = run_fresh_blinds()
        if not blind_report.get("success"):
            notify_blind_report(blind_report, source="overnight-fresh")
        out["blind_automation"] = {"mode": "fresh", "report": blind_report}
        for r in blind_report.get("runs") or []:
            if r.get("success"):
                log(
                    f"  {r.get('blind_id')}: {r.get('composite')}% "
                    f"passed={r.get('passed')}"
                )
    elif cycle_n % 4 == 0:
        blinds = agent_benchmarks.list_blinds(AGENT)
        blind_runs = []
        for b in blinds[:2]:
            blind_id = b.get("id") or str(b.get("_file", "")).replace(".yaml", "")
            if not blind_id:
                continue
            r = agent_benchmarks.run_blind(AGENT, blind_id)
            agent_benchmarks.save_blind_result(r)
            blind_runs.append(r)
            log(f"blind re-score {blind_id}: composite={r.get('composite')}% passed={r.get('passed')}")
        out["blind_runs"] = blind_runs
    return out or None


def run_cycle(state: dict[str, Any], cfg: dict[str, Any], *, focus: str = "") -> dict[str, Any]:
    from learning_agent import db
    from learning_agent.core import (
        agent_action_journal,
        agent_model_parity,
        finetune,
        overnight_runtime,
        raven_readiness,
    )

    state["cycle"] = int(state.get("cycle", 0)) + 1
    cycle_n = state["cycle"]
    _configure_cycle_runtime(cycle_n)

    focus_key = focus or os.environ.get("FINANCE_OVERNIGHT_FOCUS", "")
    topics = _pick_teacher_topics(cfg, focus=focus_key)
    ship_topic = _ship_train_topic()
    if ship_topic:
        log(f"Ship-aligned topic: {ship_topic[:80]}")
    topic_idx = int(state.get("topic_index", 0)) % max(1, len(topics))
    from learning_agent.core import finance_training_directives

    overrides = finance_training_directives.get_cycle_overrides()
    if overrides.get("force_dimension") and int(overrides.get("remaining") or 0) > 0:
        dimension = str(overrides["force_dimension"])
        log(f"directive override: dim={dimension} rest={overrides.get('remaining')}")
        finance_training_directives.tick_cycle_override()
    else:
        dimension = _pick_dimension(state, cfg, focus=focus_key)

    reasoning_before = _reasoning_score()
    current_teacher_topic = topics[topic_idx].get("topic") if topics else None

    label = "L6-operacional" if focus_key == "l6-operational" else "qualidade"
    log(f"=== Ciclo finance-lead #{cycle_n} dim={dimension} ({label}) reasoning={reasoning_before} ===")

    if focus_key == "l6-operational":
        _run_l6_operational_sprint(cycle_n)

    db.init_db()

    def _pairs_count() -> int:
        with db.get_connection() as c:
            return int(c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0])

    pairs_before = db.run_db_retry(_pairs_count)

    from learning_agent.core import finance_lead_engine

    need_full_verify = (
        dimension == "reasoning"
        or bool(state.pop("force_reasoning_remediation", False))
        or focus_key == "l6-operational"
        or cycle_n % 3 == 0
    )
    engine = finance_lead_engine.run_quality_cycle(
        cycle_n=cycle_n,
        dimension=dimension,
        topic=current_teacher_topic,
        ship_topic=ship_topic,
        full_verify=need_full_verify,
    )
    journal_study = db.run_db_retry(
        lambda: agent_action_journal.complete_action_cycle(
            AGENT,
            "finance_quality_cycle",
            f"{dimension} — {current_teacher_topic or 'estudo'}",
            engine,
            project=PROJECT,
        )
    )
    log(
        f"estudo: distilled={engine.get('distilled')} "
        f"curriculum=L{engine.get('curriculum_level')}→L{engine.get('target_level')} "
        f"journal={journal_study.get('journal', {}).get('action_id')} "
        f"full_verify={need_full_verify}"
    )

    if focus_key != "l6-operational" and cycle_n % 5 == 0:
        from learning_agent.core import finance_consolidation

        cons = finance_consolidation.run_phase1_consolidation(full=(cycle_n % 10 == 0))
        log(
            f"consolidacao F1: proof_gate={cons.get('proof_gate_ok')} "
            f"quiz_reviewed={cons.get('quiz_items_reviewed')}"
        )

    teacher_result = None
    distill_topic = ship_topic or (current_teacher_topic if topics else None)
    profile = overnight_runtime.load_snapshot().get("profile") or "raven_groq"
    if (
        distill_topic
        and overnight_runtime.should_distill_teacher(cycle_n)
        and profile != "batch_32b"
    ):
        tags = ["finance", "ship-aligned"] if ship_topic else (topics[topic_idx].get("tags") or ["finance"])
        log(f"teacher topic: {distill_topic[:80]}")
        teacher_result = _distill_teacher_topic(distill_topic, tags if isinstance(tags, list) else ["finance"])
        if topics and not ship_topic:
            state["topic_index"] = topic_idx + 1
        db.run_db_retry(
            lambda: agent_action_journal.complete_action_cycle(
                AGENT,
                "distill_topic",
                distill_topic,
                teacher_result or {"success": False, "error": "distill failed"},
                project=PROJECT,
            )
        )
    elif profile == "batch_32b" and distill_topic:
        log(f"batch 32B: destilacao pesada adiada para fim do ciclo (#{cycle_n})")

    parity = engine.get("parity_score")
    if (cycle_n % 6 == 0 or dimension == "reasoning") and not parity:
        try:
            parity_result = agent_model_parity.run_strict_parity_assessment(
                AGENT, broadcast_observer=False
            )
            parity = parity_result.get("composite_score")
            db.run_db_retry(
                lambda: agent_action_journal.complete_action_cycle(
                    AGENT,
                    "model_parity_assessment",
                    f"parity ciclo {cycle_n}",
                    parity_result,
                    project=PROJECT,
                )
            )
            log(f"L6 parity: score={parity}")
        except Exception as exc:
            agent_action_journal.log_action(
                AGENT,
                "model_parity_assessment",
                topic=f"ciclo {cycle_n}",
                project=PROJECT,
                success=False,
                error=str(exc)[:500],
            )

    if profile == "batch_32b" and distill_topic and overnight_runtime.should_distill_teacher(cycle_n):
        overnight_runtime.apply_profile("batch_32b")
        log(f"batch 32B distill: {distill_topic[:80]}")
        tags = topics[topic_idx].get("tags") if topics else ["finance", "batch-32b"]
        teacher_result = _distill_teacher_topic(
            distill_topic, tags if isinstance(tags, list) else ["finance", "batch-32b"]
        )

    if focus_key != "l6-operational":
        dim_idx = int(state.get("dim_index", 0)) % len(DIMENSIONS)
        state["dim_index"] = dim_idx + 1

    pairs_after = db.run_db_retry(_pairs_count)

    export = finetune.export_training_data(min_pairs=0)
    hf = finetune.export_hf_sft_dataset()
    brain_ok = _maybe_brain(pairs_after, state, every=5)

    readiness = raven_readiness.assess_readiness()
    reasoning_after = _reasoning_score()
    cycle_success = True
    if reasoning_before is not None and reasoning_after is not None:
        cycle_success = reasoning_after >= reasoning_before
        if not cycle_success:
            state["force_reasoning_remediation"] = True
            log(
                f"ciclo #{cycle_n} NAO elevou reasoning "
                f"({reasoning_before}->{reasoning_after}) — proximo ciclo forca reasoning"
            )
        else:
            state.pop("force_reasoning_remediation", None)
            log(f"reasoning OK: {reasoning_before}->{reasoning_after}")

    summary = {
        "cycle": cycle_n,
        "agent": AGENT,
        "project": PROJECT,
        "quality_mode": True,
        "focus": focus_key or None,
        "dimension": dimension,
        "runtime_profile": profile,
        "pairs_before": pairs_before,
        "pairs_after": pairs_after,
        "pairs_added": pairs_after - pairs_before,
        "study_distilled": engine.get("distilled"),
        "teacher_topic": current_teacher_topic,
        "teacher_distilled": bool(teacher_result and teacher_result.get("success")),
        "parity_score": parity,
        "curriculum_level": engine.get("curriculum_level"),
        "target_level": engine.get("target_level"),
        "training_examples": export.get("examples"),
        "readiness_pct": readiness["summary"]["readiness_pct"],
        "brain_refreshed": brain_ok,
        "hf_dataset": hf.get("path"),
        "motor": "finance_lead_engine",
        "reasoning_before": reasoning_before,
        "reasoning_after": reasoning_after,
        "cycle_success": cycle_success,
        "full_verify": need_full_verify,
    }
    Path("data/finance_lead_overnight_last.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _save_state(state)
    log(f"resumo: {json.dumps(summary, ensure_ascii=False)}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Overnight finance-lead evolution")
    parser.add_argument("--until", type=str, default="", help="Parar HH:MM ou 2026-06-11T05:30")
    parser.add_argument("--hours", type=float, default=0, help="Alternativa: rodar N horas")
    parser.add_argument("--interval", type=int, default=1800, help="Segundos entre ciclos (default 30min qualidade)")
    parser.add_argument("--max-cycles", type=int, default=1, help="Ciclos por sessão (default 1 — qualidade Ship)")
    parser.add_argument(
        "--focus",
        type=str,
        default="",
        choices=["", "l6-operational"],
        help="l6-operational: quiz, reasoning, proof gate, lacunas, blind",
    )
    args = parser.parse_args()

    if args.focus:
        os.environ["FINANCE_OVERNIGHT_FOCUS"] = args.focus

    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("RAG_DISABLE_CHROMA", "true")
    os.environ.pop("EVOLUTION_SKIP_DISTILL", None)
    os.environ.pop("EVOLUTION_LIGHT_STUDY", None)
    os.environ.setdefault("AUTO_PROOFS", "false")
    os.environ.setdefault("AUTO_SYNC", "false")

    if not _check_vast_tunnel():
        from learning_agent.core import overnight_runtime

        if not overnight_runtime.student_api_ready():
            log("AVISO: nem Vast nem Raven/Groq disponiveis — abortando overnight")
            print(
                "Erro: inicie Ollama (raven) ou vast-session.ps1 antes do overnight.",
                file=sys.stderr,
            )
            return 1
        log("Vast offline — fallback raven+Groq (pratica diurna / destilacao leve)")

    end_at: datetime | None = None
    if args.until:
        end_at = _parse_until(args.until)
    elif args.hours > 0:
        end_at = datetime.now() + timedelta(hours=args.hours)
    else:
        end_at = _parse_until("06:00")

    log(f"Início overnight finance-lead — até {end_at.isoformat(timespec='minutes')} max_cycles={args.max_cycles} focus={args.focus or 'default'}")
    _configure_cycle_runtime(int(_load_state().get("cycle", 0)) + 1)
    log(f"STUDENT={os.environ.get('STUDENT_MODEL')} CHAT={os.environ.get('CHAT_MODEL')} profile={os.environ.get('OVERNIGHT_RUNTIME_PROFILE')}")

    cfg = _load_prompts()
    state = _load_state()
    cycles_done = 0

    while datetime.now() < end_at:
        if args.max_cycles and cycles_done >= args.max_cycles:
            log(f"Limite de ciclos ({args.max_cycles}) atingido")
            break
        try:
            run_cycle(state, cfg, focus=args.focus)
            cycles_done += 1
        except KeyboardInterrupt:
            log("Interrompido pelo usuário")
            return 0
        except Exception as exc:
            log(f"ciclo com erro: {exc!r}")

        remaining = (end_at - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        sleep_s = min(args.interval, int(remaining))
        log(f"Próximo ciclo em {sleep_s}s (restam {remaining/3600:.1f}h)")
        time.sleep(max(120, sleep_s))

    log(f"Encerrado — {cycles_done} ciclos")

    from learning_agent.core import ship_pipeline

    mode = ship_pipeline.load_operating_mode()
    if cycles_done > 0 and mode.get("ship", {}).get("auto_after_train", True):
        try:
            from learning_agent.core import ship_autonomous

            auto = ship_autonomous.run_autonomous_queue(
                max_items=int(mode.get("ship", {}).get("max_auto_items_per_run", 2)),
            )
            log(f"ship_autonomous: ok={auto.get('ok')} processed={auto.get('processed')}")
        except Exception as exc:
            log(f"ship_autonomous falhou: {exc!r}")

    if os.environ.get("MORNING_SHIP_007", "true").lower() not in {"0", "false", "no"}:
        try:
            from learning_agent.scripts.run_morning_ship_007 import run_morning_ship_007

            morning = run_morning_ship_007()
            log(f"morning_ship_007: success={morning.get('success')}")
        except Exception as exc:
            log(f"morning_ship_007 falhou: {exc!r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
