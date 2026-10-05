"""Metodologia de treino — ciclo pedagógico por agente (Cursor mentor + pares + provas).

Substitui o loop genérico (destilar a cada 15min + ações aleatórias) por:

  diagnosticar → estudar (Cursor) → trocar com par → praticar → verificar → destilar → closure

Um agente por sessão; prioridade para quem está abaixo do L6 strict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from learning_agent.config import (
    DATA_DIR,
    MODEL_PARITY_STATE_PATH,
    MODEL_PARITY_STRICT_MIN_SCORE,
)
from learning_agent.core import (
    agent_autonomy,
    agent_learning_loop,
    agent_model_parity,
    cursor_mentor,
    distillation,
    knowledge,
)
from learning_agent.core.agent_capability import CORE_AGENTS

STATE_PATH = DATA_DIR / "agent_study_state.json"

PRACTICE_BY_ARCHETYPE: dict[str, str] = {
    "backend": "real_code_sprint",
    "frontend": "execute_micro_sprint",
    "qa-inspector": "proof_gate",
    "data": "code_walk",
    "debug-optimizer": "debug_sweep",
    "custom": "weak_area_drill",
}


def _load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"rotation_index": 0, "last_scores": {}, "sessions": 0}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parity_scores() -> dict[str, float]:
    if not MODEL_PARITY_STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(MODEL_PARITY_STATE_PATH.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
        return {
            slug: float(row.get("composite_score", 0))
            for slug, row in agents.items()
            if row.get("assessed")
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _parity_dimensions(slug: str) -> dict[str, float]:
    if not MODEL_PARITY_STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(MODEL_PARITY_STATE_PATH.read_text(encoding="utf-8"))
        dims = data.get("agents", {}).get(slug, {}).get("dimensions", {})
        return {
            k: float(v.get("score", 0))
            for k, v in dims.items()
            if isinstance(v, dict) and v.get("score") is not None
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def _weak_dimensions(slug: str, *, min_score: int | None = None) -> list[str]:
    """Dimensões abaixo da meta L6 strict (não só composite)."""
    threshold = MODEL_PARITY_STRICT_MIN_SCORE if min_score is None else min_score
    return [dim for dim, score in _parity_dimensions(slug).items() if score < threshold]


def _needs_strict_parity(slug: str) -> bool:
    """True se composite ou qualquer dimensão cognitiva estiver abaixo da meta L6."""
    scores = _parity_scores()
    composite = scores.get(slug, 0)
    if composite < MODEL_PARITY_STRICT_MIN_SCORE:
        return True
    return bool(_weak_dimensions(slug))


def _weakest_dimension(slug: str) -> str:
    dims = _parity_dimensions(slug)
    if not dims:
        return "decision"
    return min(dims.keys(), key=lambda k: dims[k])


def pick_next_agent() -> str:
    """Prioriza agente com menor score L6; senão rotação."""
    from learning_agent.core import agent_collaboration

    state = _load_state()
    scores = _parity_scores()
    below = [
        a
        for a in CORE_AGENTS
        if a in scores and scores[a] < MODEL_PARITY_STRICT_MIN_SCORE
    ]
    if below:
        return min(below, key=lambda a: scores[a])

    idx = int(state.get("rotation_index", 0)) % len(CORE_AGENTS)
    state["rotation_index"] = idx + 1
    _save_state(state)
    return CORE_AGENTS[idx]


def _finance_overnight_running() -> bool:
    try:
        from learning_agent.core.finance_status import _overnight_running

        return bool(_overnight_running())
    except Exception:
        return False


def pick_next_maintenance_agent() -> str:
    """Rodada leve — só agentes de manutenção; nunca compete com finance overnight."""
    from learning_agent.core.ship_pipeline import load_operating_mode

    mode = load_operating_mode()
    agents = list((mode.get("maintenance") or {}).get("agents") or [])
    agents = [str(a).strip().lower().replace("_", "-") for a in agents if a]
    if not agents:
        agents = [a for a in CORE_AGENTS if a != "finance-lead"]
    if _finance_overnight_running():
        agents = [a for a in agents if a != "finance-lead"]
    if not agents:
        agents = [a for a in CORE_AGENTS if a != "finance-lead"]

    state = _load_state()
    idx = int(state.get("maintenance_rotation_index", 0)) % len(agents)
    state["maintenance_rotation_index"] = idx + 1
    _save_state(state)
    return agents[idx]


def _phase_diagnose(slug: str) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    scores = _parity_scores()
    weak = _weakest_dimension(slug)
    manifest = agent_collaboration._load_manifest(slug) or {}
    weak_dims = _weak_dimensions(slug)
    return {
        "agent": slug,
        "composite_before": scores.get(slug),
        "weakest_dimension": weak,
        "weak_dimensions": weak_dims,
        "archetype": manifest.get("archetype", "custom"),
        "needs_l6": _needs_strict_parity(slug),
    }


def _phase_practice(slug: str, archetype: str, topic: str) -> dict[str, Any]:
    action = PRACTICE_BY_ARCHETYPE.get(archetype, "execute_micro_sprint")
    try:
        return agent_autonomy.execute_autonomy_action(
            action,
            topic=f"[{slug}] {topic}",
        )
    except Exception as exc:
        return {"success": False, "action": action, "error": str(exc)[:200]}


def _phase_distill(slug: str, session_summary: str, dimension: str) -> dict[str, Any] | None:
    """Destila só após sessão de estudo — qualidade > volume."""
    if not distillation.is_configured() or len(session_summary) < 80:
        return None
    teacher_body = (
        f"## Sessão de estudo estruturada — {slug}\n"
        f"**Dimensão:** {dimension}\n**Mentor:** Cursor\n\n"
        f"{session_summary[:3500]}"
    )
    try:
        return distillation.distill_from_teacher_content(
            f"[Estudo] {slug} — {dimension}",
            teacher_body,
            source_ref="cursor-study-session",
            teacher_model=f"cursor-study-{slug}",
            tags=["study-session", f"agent:{slug}", f"dimension:{dimension}"],
            sync_cloud=False,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}


def _evolution_light() -> bool:
    import os

    return os.environ.get("EVOLUTION_LIGHT_STUDY", "").lower() in {"1", "true", "yes", "on"}


def _evolution_web_research_enabled() -> bool:
    import os

    return os.environ.get("EVOLUTION_WEB_RESEARCH", "true").lower() in {"1", "true", "yes", "on"}


def run_study_session(
    agent: str | None = None,
    *,
    dimension: str | None = None,
    broadcast_observer: bool = False,
    full_verify: bool = True,
    light: bool | None = None,
) -> dict[str, Any]:
    """Uma sessão completa de treino para um agente."""
    from learning_agent.core import agent_collaboration

    light_mode = _evolution_light() if light is None else light
    slug = (agent or pick_next_agent()).strip().lower().replace("_", "-")
    state = _load_state()
    phases: dict[str, Any] = {}

    phases["diagnose"] = _phase_diagnose(slug)
    dimension = dimension or phases["diagnose"]["weakest_dimension"]
    archetype = phases["diagnose"]["archetype"]

    phases["study_cursor"] = cursor_mentor.run_cursor_mentor_session(
        slug, dimension, sync_cloud=False
    )
    domain_label = "investimento PF" if slug == "finance-lead" else "engenharia de software"
    topic = f"{dimension} em {domain_label} — {slug}"

    if light_mode and _evolution_web_research_enabled():
        try:
            phases["web_research"] = agent_collaboration.agent_research_gaps(
                slug,
                max_topics=1,
                extra_topics=[topic, phases["diagnose"].get("weakest_dimension", "")],
            )
        except Exception as exc:
            phases["web_research"] = {"success": False, "error": str(exc)[:200]}

    if light_mode:
        phases["peer_exchange"] = {"success": True, "skipped": True, "reason": "evolution_light"}
        phases["practice"] = {"success": True, "skipped": True, "reason": "evolution_light"}
    elif slug == "finance-lead":
        from learning_agent.core import finance_lead_engine

        phases["peer_exchange"] = cursor_mentor.run_peer_study_round(slug)
        phases["practice"] = finance_lead_engine.run_finance_practice(dimension, topic)
    else:
        phases["peer_exchange"] = cursor_mentor.run_peer_study_round(slug)
        phases["practice"] = _phase_practice(slug, archetype, topic)

    if light_mode:
        phases["verify"] = {"success": True, "skipped": True, "reason": "evolution_light"}
        phases["distill"] = None
        phases["closure"] = {"success": True, "skipped": True, "reason": "evolution_light"}
    else:
        if full_verify and phases["diagnose"].get("needs_l6"):
            if slug == "finance-lead" and dimension == "reasoning":
                from learning_agent.core import finance_lead_engine

                phases["reasoning_drill"] = finance_lead_engine.run_reasoning_l6_drill(
                    broadcast_observer=broadcast_observer
                )
            phases["verify"] = agent_model_parity.run_strict_parity_assessment(
                slug, broadcast_observer=broadcast_observer
            )
        else:
            phases["verify"] = agent_learning_loop.run_peer_quiz(
                target=slug, broadcast_observer=broadcast_observer
            )

        summary_parts = [
            str(phases["study_cursor"].get("distillation", {}).get("topic", "")),
            str(phases["practice"].get("plan") or phases["practice"].get("topic", ""))[:500],
        ]
        session_summary = "\n".join(p for p in summary_parts if p)
        phases["distill"] = _phase_distill(slug, session_summary, dimension)

        parent = phases["practice"].get("action") or "study_session"
        phases["closure"] = agent_learning_loop.run_learning_closure(
            parent,
            topic,
            phases["practice"],
            agent=slug,
            broadcast_observer=broadcast_observer,
        )

    scores_after = _parity_scores()
    state["sessions"] = int(state.get("sessions", 0)) + 1
    state.setdefault("last_scores", {})[slug] = scores_after.get(slug)
    _save_state(state)

    composite_after = None
    if isinstance(phases.get("verify"), dict):
        composite_after = phases["verify"].get("composite_score")

    knowledge.add_note(
        f"[Estudo] Sessão {slug}",
        json.dumps(
            {k: v.get("success", v) if isinstance(v, dict) else str(v)[:100] for k, v in phases.items()},
            ensure_ascii=False,
            indent=2,
        )[:4000],
        tags=["study-session", f"agent:{slug}", "methodology"],
        sync_cloud=False,
    )

    return {
        "success": True,
        "action": "agent_study_session",
        "methodology": "diagnose→cursor→peer→practice→verify→distill→closure",
        "agent": slug,
        "dimension": dimension,
        "composite_after": composite_after,
        "distilled": bool(phases.get("distill") and phases["distill"].get("success")),
        "phases": phases,
    }


def run_ecosystem_study_round(*, maintenance: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Uma rodada: um agente passa pelo ciclo completo."""
    agent = pick_next_maintenance_agent() if maintenance else pick_next_agent()
    return run_study_session(agent, **kwargs)
