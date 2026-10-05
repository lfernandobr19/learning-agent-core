"""Preparação total da Raven — critérios mensuráveis até software completo de alto nível."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable

from learning_agent import db
from learning_agent.config import (
    RAVEN_BASE_MODEL,
    RAVEN_MIN_CURSOR_PAIRS,
    RAVEN_MIN_DISTILL_PAIRS,
    RAVEN_MIN_L6_SCORE,
    RAVEN_MIN_PAIRS_PER_DOMAIN,
    RAVEN_MIN_TRAINING_EXAMPLES,
    RAVEN_PREPARED_BASE_MODELS,
    RAVEN_READINESS_STATE_PATH,
    STUDENT_FINETUNE_MODEL,
    STUDENT_MODEL,
)
from learning_agent.core import agent_capability, finetune, software_excellence

NORTH_STAR = (
    "A Raven estará totalmente preparada quando o cérebro local for de alto nível (base ≥14B), "
    "o corpus de destilação cobrir todos os domínios, os agentes atingirem paridade L6, "
    "e a fábrica de software estiver verde — capaz de entregar produtos completos sob demanda."
)

DOMAIN_TAGS: dict[str, list[str]] = {
    "backend": ["backend", "fastapi", "api", "postgresql", "async"],
    "frontend": ["frontend", "react", "typescript", "css", "a11y"],
    "qa": ["qa", "teste", "pytest", "vitest", "e2e"],
    "data": ["data", "rag", "embedding", "sqlite", "pipeline"],
    "reliability": ["reliability", "observabilidade", "resiliência", "debug", "proof"],
    "agents": ["agent", "orquestra", "mcp", "playbook", "scaffold"],
}

MODEL_TIERS: list[dict[str, str]] = [
    {"id": "7b", "label": "Base 7B", "example": "qwen2.5:7b", "role": "Destilação rápida"},
    {"id": "14b", "label": "Cérebro 14B", "example": "qwen2.5:14b", "role": "Raven runtime (recomendado 16GB RAM)"},
    {"id": "32b+", "label": "Cérebro 32B+", "example": "qwen2.5:32b", "role": "Alto nível — requer 32GB+ RAM ou GPU forte"},
]

ProbeFn = Callable[[], bool]


def _count_pairs_matching(pattern: str) -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM distillation_pairs
                WHERE topic LIKE ? OR teacher_output LIKE ? OR source_ref LIKE ?
                """,
                (f"%{pattern}%", f"%{pattern}%", f"%{pattern}%"),
            ).fetchone()[0]
        )


def _count_cursor_pairs() -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(
            conn.execute(
                """
                SELECT COUNT(*) FROM distillation_pairs
                WHERE teacher_model LIKE '%cursor%' OR source_ref LIKE '%cursor%'
                """
            ).fetchone()[0]
        )


def _domain_pair_counts() -> dict[str, int]:
    db.init_db()
    counts: dict[str, int] = {}
    with db.get_connection() as conn:
        rows = conn.execute("SELECT id, topic, teacher_output FROM distillation_pairs").fetchall()
    for domain, keywords in DOMAIN_TAGS.items():
        n = 0
        for row in rows:
            blob = f"{row['topic']} {row['teacher_output']}".lower()
            if any(kw.lower() in blob for kw in keywords):
                n += 1
        counts[domain] = n
    return counts


def _base_model_tier() -> str:
    base = RAVEN_BASE_MODEL.lower()
    if any(x in base for x in ("32b", "70b")):
        return "32b+"
    if "14b" in base:
        return "14b"
    return "7b"


def _ollama_has_model(name: str) -> bool:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=20)
        return name in (r.stdout or "")
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def _l6_agents_ready() -> tuple[int, int]:
    from learning_agent.config import MODEL_PARITY_STATE_PATH

    if not MODEL_PARITY_STATE_PATH.is_file():
        return 0, len(agent_capability.CORE_AGENTS)
    try:
        data = json.loads(MODEL_PARITY_STATE_PATH.read_text(encoding="utf-8"))
        agents = data.get("agents", {})
        ready = 0
        for slug in agent_capability.CORE_AGENTS:
            row = agents.get(slug, {})
            if row.get("assessed") and float(row.get("composite_score", 0)) >= RAVEN_MIN_L6_SCORE:
                ready += 1
        return ready, len(agent_capability.CORE_AGENTS)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0, len(agent_capability.CORE_AGENTS)


def _training_examples() -> int:
    return int(finetune.export_training_data(min_pairs=0).get("examples", 0))


def _total_distill_pairs() -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0])


READINESS_PHASES: list[dict[str, Any]] = [
    {
        "id": "model_tier_14b",
        "phase": 1,
        "title": "Elevar cérebro para 14B+",
        "description": f"RAVEN_BASE_MODEL em tier ≥14B (atual: {RAVEN_BASE_MODEL})",
        "action": "upgrade_base_model",
        "probe": lambda: _base_model_tier() in {"14b", "32b+"},
    },
    {
        "id": "raven_model_live",
        "phase": 1,
        "title": "Modelo raven ativo no Ollama",
        "description": f"{STUDENT_FINETUNE_MODEL} criado a partir de {RAVEN_BASE_MODEL}",
        "action": "brain_pipeline",
        "probe": lambda: _ollama_has_model(STUDENT_FINETUNE_MODEL),
    },
    {
        "id": "corpus_volume",
        "phase": 2,
        "title": "Corpus de destilação amplo",
        "description": f"Pelo menos {RAVEN_MIN_DISTILL_PAIRS} pares professor→aluno",
        "action": "distillation_batch",
        "probe": lambda: _total_distill_pairs() >= RAVEN_MIN_DISTILL_PAIRS,
    },
    {
        "id": "corpus_cursor",
        "phase": 2,
        "title": "Destilação via Cursor (professor)",
        "description": f"Pelo menos {RAVEN_MIN_CURSOR_PAIRS} pares com professor Cursor",
        "action": "distill_from_cursor",
        "probe": lambda: _count_cursor_pairs() >= RAVEN_MIN_CURSOR_PAIRS,
    },
    {
        "id": "corpus_domains",
        "phase": 2,
        "title": "Cobertura por domínio",
        "description": f"Cada domínio com sinais de ≥{RAVEN_MIN_PAIRS_PER_DOMAIN} pares",
        "action": "distillation_batch",
        "probe": lambda: all(
            v >= RAVEN_MIN_PAIRS_PER_DOMAIN for v in _domain_pair_counts().values()
        ),
    },
    {
        "id": "training_dataset",
        "phase": 3,
        "title": "Dataset de treino maduro",
        "description": f"≥{RAVEN_MIN_TRAINING_EXAMPLES} exemplos exportados",
        "action": "export_training",
        "probe": lambda: _training_examples() >= RAVEN_MIN_TRAINING_EXAMPLES,
    },
    {
        "id": "factory_ready",
        "phase": 4,
        "title": "Fábrica de software verde",
        "description": "Objetivos must da fábrica 100%",
        "action": "software_excellence_sprint",
        "probe": lambda: software_excellence.assess_excellence().get("complete", False),
    },
    {
        "id": "agents_l5",
        "phase": 4,
        "title": "5 agentes core em L5",
        "description": "Especialistas maduros no ecossistema",
        "action": "capability_assessment",
        "probe": lambda: agent_capability.assess_ecosystem()["summary"]["specialists"]
        >= len(agent_capability.CORE_AGENTS),
    },
    {
        "id": "agents_l6",
        "phase": 5,
        "title": "Paridade cognitiva L6",
        "description": f"Todos os core agents com score ≥{RAVEN_MIN_L6_SCORE}",
        "action": "model_parity_assessment",
        "probe": lambda: _l6_agents_ready()[0] >= len(agent_capability.CORE_AGENTS),
    },
    {
        "id": "delivery_proofs",
        "phase": 5,
        "title": "Provas de entrega verdes",
        "description": "Proof gate + sprints verificados em todos os agentes",
        "action": "proof_gate",
        "probe": lambda: agent_capability._recent_proof_gate_ok()
        and all(agent_capability._has_verified_sprint(a) for a in agent_capability.CORE_AGENTS),
    },
]


def _eval_phases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in READINESS_PHASES:
        probe = item.get("probe")
        met = False
        if callable(probe):
            try:
                met = bool(probe())
            except Exception:
                met = False
        row = {k: v for k, v in item.items() if k != "probe"}
        row["met"] = met
        row["status"] = "done" if met else "pending"
        out.append(row)
    return out


def assess_readiness() -> dict[str, Any]:
    """Avalia preparação total da Raven."""
    phases = _eval_phases()
    must = phases  # all phases required for "fully prepared"
    met = sum(1 for p in phases if p["met"])
    total = len(phases)
    pct = round(100.0 * met / max(total, 1), 1)
    complete = met == total

    by_phase: dict[int, list[dict[str, Any]]] = {}
    for p in phases:
        by_phase.setdefault(p["phase"], []).append(p)

    l6_ready, l6_total = _l6_agents_ready()
    factory = software_excellence.assess_excellence()

    result = {
        "success": True,
        "complete": complete,
        "north_star": NORTH_STAR,
        "summary": {
            "readiness_pct": pct,
            "phases_met": met,
            "phases_total": total,
            "status_label": "PREPARADA" if complete else "EM PREPARAÇÃO",
            "model_tier": _base_model_tier(),
            "raven_base": RAVEN_BASE_MODEL,
            "distill_student": STUDENT_MODEL,
            "raven_runtime": STUDENT_FINETUNE_MODEL,
        },
        "phases": phases,
        "by_phase": by_phase,
        "missing": [p["id"] for p in phases if not p["met"]],
        "next_phase": next((p for p in phases if not p["met"]), None),
        "corpus": {
            "total_pairs": _total_distill_pairs(),
            "cursor_pairs": _count_cursor_pairs(),
            "training_examples": _training_examples(),
            "domain_signals": _domain_pair_counts(),
            "targets": {
                "min_pairs": RAVEN_MIN_DISTILL_PAIRS,
                "min_cursor": RAVEN_MIN_CURSOR_PAIRS,
                "min_per_domain": RAVEN_MIN_PAIRS_PER_DOMAIN,
                "min_training": RAVEN_MIN_TRAINING_EXAMPLES,
            },
        },
        "model_tiers": MODEL_TIERS,
        "hardware_note": (
            "16GB RAM: use qwen2.5:7b para destilação (rápido) e qwen2.5:14b como RAVEN_BASE_MODEL "
            "(cérebro). 32B+ exige mais RAM ou GPU."
        ),
        "l6": {"ready": l6_ready, "total": l6_total, "min_score": RAVEN_MIN_L6_SCORE},
        "factory": factory.get("summary", {}),
    }
    _persist(result)
    return result


def run_preparation_sprint(*, broadcast_observer: bool = True) -> dict[str, Any]:
    """Executa a próxima ação do roteiro de preparação."""
    from learning_agent.core import agent_autonomy, agent_collaboration, knowledge

    report = assess_readiness()
    nxt = report.get("next_phase")
    if not nxt:
        return {
            "success": True,
            "action": "raven_preparation_sprint",
            "complete": True,
            "message": "Raven totalmente preparada",
        }

    action = nxt.get("action", "distillation_batch")
    title = nxt.get("title", nxt["id"])

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Preparação Raven: «{title}» — ação «{action}»",
            level="raven-readiness",
        )

    if action == "upgrade_base_model":
        result = {
            "success": True,
            "action": action,
            "hint": (
                f"Defina RAVEN_BASE_MODEL=qwen2.5:14b no .env, rode `ollama pull qwen2.5:14b`, "
                f"depois `run_brain_pipeline`. Tier preparado: {RAVEN_PREPARED_BASE_MODELS}"
            ),
            "current_base": RAVEN_BASE_MODEL,
            "recommended": "qwen2.5:14b",
        }
    elif action == "distill_from_cursor":
        result = {
            "success": True,
            "action": action,
            "hint": "Use MCP distill_from_cursor com conteúdo gerado no Cursor como professor.",
        }
    else:
        result = agent_autonomy.execute_autonomy_action(action)

    knowledge.add_note(
        f"[Raven preparação] {title}",
        f"Fase: {nxt.get('phase')}\nAção: {action}\n\n{json.dumps(result, ensure_ascii=False)[:2000]}",
        tags=["raven-readiness", f"phase:{nxt.get('phase')}", f"objective:{nxt['id']}"],
    )

    fresh = assess_readiness()
    return {
        "success": True,
        "action": "raven_preparation_sprint",
        "complete": fresh["complete"],
        "executed": action,
        "phase": nxt,
        "result": result,
        "readiness": fresh["summary"],
    }


def _persist(report: dict[str, Any]) -> None:
    slim = {
        "complete": report["complete"],
        "north_star": report["north_star"],
        "summary": report["summary"],
        "missing": report["missing"][:12],
        "next_phase_id": (report.get("next_phase") or {}).get("id"),
        "corpus": report.get("corpus", {}),
    }
    RAVEN_READINESS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RAVEN_READINESS_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)
