"""Motor Raven — finance-lead (qualidade > quantidade).

Integra auxílio estilo Cursor (mentor + proxy Sonnet), pesquisa web, currículo,
prática (backtest/journal), paridade L6 e autonomia — espelhando agentes core.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT, TEACHER_API_BASE, TEACHER_API_KEY, TEACHER_MODEL
from learning_agent.core import (
    agent_action_journal,
    agent_collaboration,
    agent_curriculum,
    agent_learning_loop,
    agent_model_parity,
    agent_study_methodology,
    cursor_mentor,
    distillation,
    knowledge,
    llm as llm_core,
)

AGENT = "finance-lead"
PROJECT = "finance-lead-mastery"
BACKTEST = PROJECT_ROOT / "agents" / "projects" / "finance-lead" / "scripts" / "paper_backtest.py"


def _pick_curriculum_topic(milestone: dict[str, Any]) -> str:
    topics = (milestone.get("milestone") or {}).get("topics") or []
    if topics:
        return str(topics[0])
    return str((milestone.get("milestone") or {}).get("title") or "investimento PF")


def run_cursor_proxy_lesson(
    dimension: str,
    topic: str,
    *,
    sync_cloud: bool = False,
) -> dict[str, Any]:
    """Professor API como proxy tier Cursor — lição dinâmica por tópico."""
    if not TEACHER_API_KEY:
        return {"success": False, "skipped": True, "reason": "TEACHER_API_KEY ausente"}

    system = (
        "Você é o mentor Cursor (tier Sonnet) especializado em finanças pessoais e investimento PF Brasil. "
        f"Dimensão: {dimension}. Produza lição técnica em markdown com: "
        "conceitos precisos, trade-offs quando couber, critérios mensuráveis, "
        "paper trading only, zero promessa de retorno. Máx. 800 palavras."
    )
    user = f"Tópico: {topic}\n\nGere lição completa para destilação no agente finance-lead."
    try:
        content = llm_core.chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url=TEACHER_API_BASE,
            api_key=TEACHER_API_KEY,
            model=TEACHER_MODEL,
            max_tokens=1200,
            temperature=0.35,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}

    title = f"[Cursor Proxy/{dimension}] {topic[:60]}"
    row = distillation.distill_from_teacher_content(
        title,
        content,
        source_ref="cursor-proxy-teacher",
        teacher_model=f"cursor-proxy-{TEACHER_MODEL}",
        tags=["cursor-proxy", f"agent:{AGENT}", f"dimension:{dimension}", "finance"],
        sync_cloud=sync_cloud,
    )
    knowledge.add_note(
        title,
        content[:2500],
        tags=["cursor-proxy", f"agent:{AGENT}", f"dimension:{dimension}"],
        sync_cloud=sync_cloud,
    )
    return {"success": True, "action": "cursor_proxy_lesson", "distillation": row, "topic": topic}


def run_finance_practice(dimension: str, topic: str) -> dict[str, Any]:
    """Prática verificável — backtest reprodutível + drill de decisão."""
    results: dict[str, Any] = {"success": True, "action": "finance_practice", "dimension": dimension}

    if BACKTEST.is_file():
        proc = subprocess.run(
            [sys.executable, str(BACKTEST), "--json"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd=str(PROJECT_ROOT),
        )
        results["backtest"] = {
            "passed": proc.returncode == 0,
            "detail": (proc.stdout or proc.stderr)[-300:],
        }
        if proc.returncode == 0:
            try:
                results["backtest"]["metrics"] = json.loads(proc.stdout.strip())
            except json.JSONDecodeError:
                pass

    if dimension == "decision":
        drill = agent_learning_loop.run_weak_area_drill(AGENT, broadcast_observer=False)
        results["decision_drill"] = drill
    elif dimension == "knowledge" and topic:
        research = agent_collaboration.agent_research_gaps(
            AGENT, max_topics=1, extra_topics=[topic]
        )
        results["knowledge_research"] = research

    results["passed"] = bool(
        results.get("backtest", {}).get("passed", True)
        and results.get("decision_drill", {}).get("success", True)
        and results.get("knowledge_research", {}).get("success", True)
    )
    return results


def run_web_research(topic: str, *, cycle_n: int) -> dict[str, Any]:
    """Pesquisa web indexada — alternada para qualidade (não spam)."""
    if cycle_n % 2 == 0:
        return {"success": True, "skipped": True, "reason": "ciclo par — qualidade > volume de buscas"}
    if not topic.strip():
        return {"success": False, "error": "tópico vazio"}
    return agent_collaboration.agent_research_gaps(AGENT, max_topics=1, extra_topics=[topic])


def run_autonomy_from_curriculum(*, cycle_n: int) -> dict[str, Any] | None:
    """Executa ação sugerida pelo currículo a cada 4 ciclos."""
    if cycle_n % 4 != 0:
        return None
    return agent_learning_loop.run_curriculum_milestone(AGENT, broadcast_observer=False)


def run_quality_cycle(
    *,
    cycle_n: int,
    dimension: str,
    topic: str | None = None,
    ship_topic: str | None = None,
    full_verify: bool = False,
) -> dict[str, Any]:
    """Ciclo completo finance-lead — Raven motor + Cursor + web + prática."""
    phases: dict[str, Any] = {}

    phases["curriculum"] = agent_curriculum.get_next_milestone(AGENT)
    focus_topic = ship_topic or topic or _pick_curriculum_topic(phases["curriculum"])

    phases["web_research"] = run_web_research(focus_topic, cycle_n=cycle_n)
    phases["cursor_proxy"] = run_cursor_proxy_lesson(dimension, focus_topic)

    from learning_agent.core import finance_economic_news, finance_training_extensions

    cur_level = int(phases["curriculum"].get("current_level") or 0)
    at_l6 = cur_level >= 6

    if at_l6 and cycle_n % 3 == 1:
        phases["economic_news"] = finance_economic_news.fetch_and_index_economic_news()
    if at_l6 and cycle_n % 4 == 2:
        phases["diversified_data"] = finance_training_extensions.run_diversified_data_fetch(
            source="auto"
        )
    if at_l6 and dimension == "knowledge" and cycle_n % 5 == 0:
        phases["microeconomics"] = finance_training_extensions.ensure_microeconomics_indexed()
    if at_l6 and dimension == "reasoning" and cycle_n % 6 == 0:
        phases["cross_validation"] = finance_training_extensions.run_cross_validation_check()

    phases["study"] = agent_study_methodology.run_study_session(
        AGENT,
        dimension=dimension,
        broadcast_observer=False,
        full_verify=full_verify,
        light=False,
    )

    # Decisão paper — DEPOIS de estudo/drill/quiz (não compete com aula prática)
    if dimension == "decision":
        from learning_agent.core import finance_decision_loop

        phases["paper_decision"] = finance_decision_loop.run_decision_cycle()

    phases["curriculum_action"] = run_autonomy_from_curriculum(cycle_n=cycle_n)

    if cycle_n % 6 == 0:
        try:
            phases["parity"] = agent_model_parity.run_strict_parity_assessment(
                AGENT, broadcast_observer=False
            )
        except Exception as exc:
            phases["parity"] = {"success": False, "error": str(exc)[:200]}

    distilled = any(
        p.get("distilled") or (p.get("distillation") or {}).get("success")
        for p in phases.values()
        if isinstance(p, dict)
    )

    agent_action_journal.complete_action_cycle(
        AGENT,
        "finance_quality_cycle",
        f"{dimension} — {focus_topic[:80]}",
        {"phases": {k: v.get("success", v) if isinstance(v, dict) else str(v)[:80] for k, v in phases.items()}},
        project=PROJECT,
    )

    return {
        "success": True,
        "action": "finance_quality_cycle",
        "agent": AGENT,
        "cycle": cycle_n,
        "dimension": dimension,
        "topic": focus_topic,
        "distilled": distilled,
        "study_distilled": phases.get("study", {}).get("distilled"),
        "parity_score": (phases.get("parity") or {}).get("composite_score"),
        "curriculum_level": phases["curriculum"].get("current_level"),
        "target_level": phases["curriculum"].get("target_level"),
        "phases": phases,
    }


REASONING_PRACTICE_LAST = PROJECT_ROOT / "data" / "finance_reasoning_practice_last.json"
REASONING_PRACTICE_SCHEDULE = PROJECT_ROOT / "data" / "finance_practice_schedule.json"

_REASONING_DRILL_MIN_MARKERS = 4


def run_reasoning_l6_drill(*, broadcast_observer: bool = False) -> dict[str, Any]:
    """Drill L6 — resposta no formato do benchmark strict antes da paridade."""
    from learning_agent.core.agent_model_parity import (
        STRICT_DIMENSION_GUIDE,
        STRICT_REASONING_MARKERS,
    )
    from learning_agent.core.cursor_mentor import CURSOR_MENTOR_LESSONS

    prompts = agent_model_parity._prompts_for(AGENT)
    parity_prompt = prompts["reasoning"]
    mentor = (CURSOR_MENTOR_LESSONS.get(AGENT) or {}).get("reasoning", "")
    guide = STRICT_DIMENSION_GUIDE["reasoning"]

    manifest = agent_collaboration._load_manifest(AGENT) or {}
    display = manifest.get("display_name", AGENT)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            AGENT,
            "Drill L6 reasoning — formato paridade (causas→passos→critério→rollback)…",
            level="reasoning-drill",
        )

    phases: dict[str, Any] = {
        "mentor": cursor_mentor.run_cursor_mentor_session(
            AGENT, "reasoning", sync_cloud=False, distill=False
        ),
    }

    system = (
        f"Você é {display}, especialista em finanças pessoais no Brasil. "
        f"FORMATO L6 (reasoning): {guide}\n\n"
        f"[Lição mentor Cursor]\n{mentor[:2000]}\n\n"
        "Responda ao cenário em português: causas ordenadas, passos numerados, "
        "critério de aceite mensurável e rollback se a mitigação falhar."
    )

    try:
        answer, model = llm_core.chat_with_fallback(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": parity_prompt},
            ],
            max_tokens=520,
            temperature=0.25,
        )
    except Exception as exc:
        return {
            "success": False,
            "action": "reasoning_l6_drill",
            "phases": phases,
            "error": str(exc)[:200],
        }

    lower = answer.lower()
    markers_found = [m for m in STRICT_REASONING_MARKERS if m in lower]
    markers_missing = [m for m in STRICT_REASONING_MARKERS if m not in lower]
    markers_met = len(markers_found) >= _REASONING_DRILL_MIN_MARKERS

    note = knowledge.add_note(
        "[Reasoning L6 drill] finance-lead — rebalanceamento macro",
        (
            f"**Prompt paridade:** {parity_prompt}\n\n"
            f"**Resposta drill:**\n{answer[:3000]}\n\n"
            f"**Marcadores L6:** ok={markers_found} | faltando={markers_missing}"
        ),
        tags=["reasoning-drill", "finance-lead", "l6-refinement", f"agent:{AGENT}"],
        sync_cloud=False,
    )

    result = {
        "success": True,
        "action": "reasoning_l6_drill",
        "parity_prompt": parity_prompt,
        "model": model,
        "markers_found": markers_found,
        "markers_missing": markers_missing,
        "markers_met": markers_met,
        "answer_preview": answer[:500],
        "note_id": note.get("note_id") or note.get("id"),
        "phases": phases,
    }

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            AGENT,
            f"Drill L6 reasoning — marcadores {len(markers_found)}/{len(STRICT_REASONING_MARKERS)} "
            f"({'ok' if markers_met else 'revisar'})",
            level="reasoning-drill-result",
        )
    return result


def run_reasoning_practice_session(*, broadcast_observer: bool = False) -> dict[str, Any]:
    """Prática real — reasoning L6: dados live, walk-forward, estudo completo, paper, paridade."""
    import os
    from datetime import datetime, timezone

    from learning_agent.core import (
        agent_capability,
        finance_decision_loop,
        finance_economic_news,
        finance_training_extensions,
    )

    os.environ["EVOLUTION_LIGHT_STUDY"] = "false"
    os.environ["AUTO_PROOFS"] = "true"
    os.environ.setdefault("FINANCE_DECISION_MODE", "autonomous_paper")

    state_path = PROJECT_ROOT / "data" / "finance_lead_overnight_state.json"
    cycle_n = 1
    if state_path.is_file():
        try:
            cycle_n = int(json.loads(state_path.read_text(encoding="utf-8")).get("cycle", 0)) + 1
        except (json.JSONDecodeError, ValueError):
            pass

    cap_before = agent_capability.compute_agent_capability(AGENT)
    reasoning_before = (cap_before.get("level_6") or {}).get("dimensions", {}).get("reasoning", {})

    phases: dict[str, Any] = {
        "diversified_data": finance_training_extensions.run_diversified_data_fetch(source="auto"),
        "cross_validation": finance_training_extensions.run_cross_validation_check(),
        "economic_news": finance_economic_news.fetch_and_index_economic_news(),
    }
    phases["quality_cycle"] = run_quality_cycle(
        cycle_n=cycle_n,
        dimension="reasoning",
        full_verify=True,
    )
    phases["peer_quiz"] = agent_learning_loop.run_peer_quiz(
        target=AGENT, broadcast_observer=broadcast_observer
    )
    phases["reasoning_drill"] = run_reasoning_l6_drill(broadcast_observer=broadcast_observer)
    try:
        phases["parity"] = agent_model_parity.run_strict_parity_assessment(
            AGENT, broadcast_observer=broadcast_observer
        )
    except Exception as exc:
        phases["parity"] = {"success": False, "error": str(exc)[:200]}
    drill = phases.get("reasoning_drill")
    parity = phases.get("parity")
    if isinstance(drill, dict) and isinstance(parity, dict) and parity.get("success"):
        reasoning_dim = (parity.get("dimensions") or {}).get("reasoning") or {}
        if reasoning_dim.get("score") is not None:
            drill["parity_reasoning_score"] = reasoning_dim["score"]
        if reasoning_dim.get("feedback"):
            drill["parity_feedback"] = str(reasoning_dim["feedback"])[:300]
    phases["paper_decision"] = finance_decision_loop.run_decision_cycle()

    cap_after = agent_capability.compute_agent_capability(AGENT)
    l6_after = cap_after.get("level_6") or {}
    reasoning_after = l6_after.get("dimensions", {}).get("reasoning", {})

    result = {
        "success": True,
        "action": "finance_reasoning_practice",
        "agent": AGENT,
        "cycle": cycle_n,
        "dimension": "reasoning",
        "focus": "ambiente real — dados live, walk-forward, paper, paridade L6",
        "reasoning_before": reasoning_before.get("score"),
        "reasoning_after": reasoning_after.get("score"),
        "composite_after": l6_after.get("composite_score"),
        "l6_operational": (l6_after.get("operational_checklist") or {}).get("eligible"),
        "parity_met": l6_after.get("parity_met"),
        "phases": phases,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    REASONING_PRACTICE_LAST.parent.mkdir(parents=True, exist_ok=True)
    REASONING_PRACTICE_LAST.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    state_path.write_text(
        json.dumps({"cycle": cycle_n, "last_dimension": "reasoning"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    agent_action_journal.complete_action_cycle(
        AGENT,
        "finance_reasoning_practice",
        f"reasoning {reasoning_before.get('score')}→{reasoning_after.get('score')}",
        {
            "l6_operational": result["l6_operational"],
            "composite_after": result["composite_after"],
        },
        project=PROJECT,
    )
    return result


def build_training_status() -> dict[str, Any]:
    """Resumo para API, Telegram e MCP."""
    from learning_agent.core import agent_capability, agent_external_completion

    cap = agent_capability.compute_agent_capability(AGENT)
    external = agent_external_completion.assess_external_completion(AGENT)
    milestone = agent_curriculum.get_next_milestone(AGENT)
    last_path = PROJECT_ROOT / "data" / "finance_lead_overnight_last.json"
    last = {}
    if last_path.is_file():
        try:
            last = json.loads(last_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    return {
        "agent": AGENT,
        "quality_mode": True,
        "capability_level": cap.get("level"),
        "capability_score": cap.get("score"),
        "external_ready": external.get("external_ready"),
        "external_pass": f"{external.get('passed_count', 0)}/{external.get('total', 5)}",
        "curriculum_current": milestone.get("current_level"),
        "curriculum_target": milestone.get("target_level"),
        "milestone_title": (milestone.get("milestone") or {}).get("title"),
        "suggested_actions": milestone.get("suggested_actions", []),
        "last_cycle": last.get("cycle"),
        "last_dimension": last.get("dimension"),
        "parity_score": last.get("parity_score"),
        "motor": "Raven + Cursor + web + notícias + dados diversificados + micro + prática",
    }
