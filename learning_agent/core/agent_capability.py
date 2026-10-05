"""Níveis de capacidade dos agentes — escala 1–5 com critérios de Especialista."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from learning_agent import db
from learning_agent.config import CAPABILITY_STATE_PATH, PROJECT_ROOT, SPRINT_ARTIFACTS_DIR
from learning_agent.core import agent_collaboration, progress, proofs

CORE_AGENTS = [
    "backend-lead",
    "frontend-lead",
    "qa-guardian",
    "data-engineer",
    "reliability-lead",
]

CAPABILITY_SCALE: dict[int, dict[str, str]] = {
    1: {
        "label": "Iniciante",
        "summary": "Poucos insights, lacunas abertas, loop de aprendizado começando.",
    },
    2: {
        "label": "Em evolução",
        "summary": "Aprendizado ativo — pesquisa, trocas e primeiras elevações.",
    },
    3: {
        "label": "Intermediário",
        "summary": "Boa troca peer, closures regulares, lacunas controladas.",
    },
    4: {
        "label": "Avançado",
        "summary": "Domínio indexado, zero lacunas críticas, alto volume de prática.",
    },
    5: {
        "label": "Especialista",
        "summary": "Provas verdes, sprint executável, quiz >80%, playbook evoluído.",
    },
    6: {
        "label": "Paridade Cursor",
        "summary": "L6 strict — conhecimento, raciocínio e decisão no tier Cursor (≥80).",
    },
}

LEVEL_5_CRITERIA = {
    "quiz_mastery_pct": 80,
    "min_closures": 5,
    "min_elevations": 5,
    "min_insights": 15,
    "max_gaps": 0,
    "proof_gate_required": True,
    "verified_sprint_required": True,
    "playbook_evolved_required": True,
}

_proof_cache: bool | None = None
_capability_depth = 0


def capability_compute_depth() -> int:
    """Profundidade de compute_agent_capability (evita recursão com currículo)."""
    return _capability_depth


RECOMMENDED_INCREMENTS: list[dict[str, str]] = [
    {"id": "event_triggers", "title": "Gatilhos por evento", "status": "implemented"},
    {"id": "mentor_pairing", "title": "Mentoria fixa", "status": "implemented"},
    {"id": "domain_curriculum", "title": "Currículo por agente", "status": "implemented"},
    {"id": "real_code_sprints", "title": "Sprints em código real", "status": "implemented"},
    {"id": "spaced_repetition", "title": "Quiz SM-2 por domínio", "status": "implemented"},
    {"id": "ide_practice", "title": "Práticas na IDE", "status": "implemented"},
    {"id": "capability_dashboard", "title": "Painel de evolução na IDE", "status": "implemented"},
    {"id": "ide_completion_objective", "title": "Aula prática IDE (paridade Cursor)", "status": "implemented"},
    {"id": "software_excellence_north", "title": "Fábrica de software de excelência", "status": "implemented"},
    {"id": "ravenna_brain_pipeline", "title": "Cérebro local raven", "status": "implemented"},
    {"id": "model_parity_l6", "title": "Paridade cognitiva L6", "status": "implemented"},
]


def _utcnow() -> str:
    return db._utcnow()


def _learning_tags(agent: str) -> list[str]:
    return agent_collaboration._learning_tags(agent)


def _base_metrics(agent: str) -> dict[str, Any]:
    gaps = agent_collaboration.detect_knowledge_gaps(agent)
    manifest = agent_collaboration._load_manifest(agent) or {}

    db.init_db()
    with db.get_connection() as conn:
        insights = conn.execute(
            "SELECT COUNT(*) AS c FROM agent_insights WHERE from_agent = ?",
            (agent,),
        ).fetchone()["c"]
        exchanges = conn.execute(
            "SELECT COUNT(*) AS c FROM agent_exchanges WHERE from_agent = ?",
            (agent,),
        ).fetchone()["c"]
        notes = conn.execute(
            "SELECT COUNT(*) AS c FROM learning_notes WHERE tags LIKE ? OR title LIKE ?",
            (f"%{agent}%", f"%{agent}%"),
        ).fetchone()["c"]
        closures = conn.execute(
            """
            SELECT COUNT(*) AS c FROM learning_notes
            WHERE tags LIKE '%learning-closure%'
              AND (tags LIKE ? OR title LIKE ?)
            """,
            (f"%agent:{agent}%", f"%{agent}%"),
        ).fetchone()["c"]
        elevations = conn.execute(
            """
            SELECT COUNT(*) AS c FROM learning_notes
            WHERE tags LIKE '%elevate%'
              AND (title LIKE ? OR tags LIKE ?)
            """,
            (f"%{agent}%", f"%agent:{agent}%"),
        ).fetchone()["c"]

    gap_n = gaps.get("gap_count", 0)
    covered = len(gaps.get("covered", []))
    raw_score = (
        insights * 3
        + covered * 4
        + closures * 6
        + elevations * 4
        + exchanges * 1.5
        + notes * 0.3
        - gap_n * 4
    )
    base_score = max(0.0, min(85.0, raw_score))

    return {
        "manifest": manifest,
        "gaps": gaps,
        "gap_count": gap_n,
        "topics_covered": covered,
        "insights_shared": insights,
        "exchanges": exchanges,
        "notes": notes,
        "learning_closures": closures,
        "elevations": elevations,
        "base_score": round(base_score, 1),
    }


def _quiz_mastery(agent: str, *, latest_per_item: bool = False) -> dict[str, Any]:
    tags = [t.lower() for t in _learning_tags(agent)]
    tags.extend([agent, agent.replace("-", " "), f"peer-{agent}"])

    db.init_db()
    with db.get_connection() as conn:
        if latest_per_item:
            rows = conn.execute(
                """
                SELECT qi.topic, qa.correct
                FROM quiz_items qi
                JOIN quiz_attempts qa ON qa.id = (
                    SELECT id FROM quiz_attempts
                    WHERE quiz_item_id = qi.id
                    ORDER BY id DESC LIMIT 1
                )
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT qi.topic, qa.correct
                FROM quiz_attempts qa
                JOIN quiz_items qi ON qi.id = qa.quiz_item_id
                """
            ).fetchall()

    relevant = []
    for row in rows:
        topic = str(row["topic"]).lower()
        if any(tag in topic for tag in tags if len(tag) >= 3):
            relevant.append(bool(row["correct"]))

    if not relevant:
        return {"pct": 0.0, "attempts": 0, "correct": 0, "met": False}

    correct = sum(1 for r in relevant if r)
    pct = round(100.0 * correct / len(relevant), 1)
    target = 85 if agent == "finance-lead" and latest_per_item else LEVEL_5_CRITERIA["quiz_mastery_pct"]
    return {
        "pct": pct,
        "attempts": len(relevant),
        "correct": correct,
        "met": pct >= target,
        "latest_per_item": latest_per_item,
    }


def _playbook_evolved(agent: str) -> bool:
    path = PROJECT_ROOT / "agents" / "projects" / agent / "playbook.md"
    if not path.is_file():
        return False
    return "## Práticas autônomas (atualizado)" in path.read_text(encoding="utf-8")


def _has_verified_sprint(agent: str) -> bool:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM learning_notes
            WHERE tags LIKE '%micro-sprint%'
              AND (tags LIKE ? OR title LIKE ? OR content LIKE ?)
            """,
            (f"%{agent}%", f"%{agent}%", "%micro_sprint_ok%"),
        ).fetchone()
        if row["c"] > 0:
            return True

    with db.get_connection() as conn:
        real = conn.execute(
            """
            SELECT COUNT(*) AS c FROM learning_notes
            WHERE tags LIKE '%real-code-sprint%' AND (tags LIKE ? OR title LIKE ?)
            """,
            (f"%{agent}%", f"%{agent}%"),
        ).fetchone()
        if real["c"] > 0:
            return True

    if SPRINT_ARTIFACTS_DIR.is_dir():
        for f in SPRINT_ARTIFACTS_DIR.glob("micro_*.py"):
            if f.is_file() and f.stat().st_size > 20:
                return True
    from learning_agent.config import AGENT_SPRINT_TESTS_DIR

    if AGENT_SPRINT_TESTS_DIR.is_dir():
        for f in AGENT_SPRINT_TESTS_DIR.glob(f"test_sprint_{agent.replace('-', '_')}*.py"):
            if f.is_file():
                return True
    return False


def _recent_proof_gate_ok() -> bool:
    """Último proof_gate global ou suite ao vivo (cache por avaliação)."""
    global _proof_cache
    if _proof_cache is not None:
        return _proof_cache

    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute(
            """
            SELECT content FROM learning_notes
            WHERE tags LIKE '%proof-gate%' OR tags LIKE '%debug-sweep%'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    if row and "PASS" in str(row["content"]).upper():
        _proof_cache = True
        return _proof_cache
    if row and "FALHOU" in str(row["content"]).upper():
        _proof_cache = False
        return _proof_cache
    suite = proofs.run_full_proof_suite()
    _proof_cache = bool(suite.get("all_passed"))
    return _proof_cache


def _level_from_base(score: float, metrics: dict[str, Any]) -> int:
    if score >= 70 and metrics["gap_count"] == 0 and metrics["learning_closures"] >= 4:
        return 4
    if score >= 45 and metrics["learning_closures"] >= 2:
        return 3
    if score >= 20 or metrics["insights_shared"] >= 5:
        return 2
    return 1


_external_status_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_EXTERNAL_STATUS_TTL = 300.0  # 5 min


def _external_completion_status(slug: str) -> dict[str, Any] | None:
    # Guarda contra recursão: probes externas rodam `pytest` em subprocesso
    # (ex.: probe_qa_smoke_suite → test_agent_ide_smoke.py) e esses testes
    # chamam /api/agents/evolution de volta. O env var é herdado pelo
    # subprocesso e interrompe o ciclo.
    if os.environ.get("RAVENNA_CAPABILITY_PROBE"):
        return None

    # Cache: as probes externas rodam pytest em subprocesso (caro). Sem cache,
    # cada chamada de assess_ecosystem() (painéis /api/excellence e
    # /api/agents/evolution) re-executaria a suíte de sprint/smoke.
    import time

    now = time.monotonic()
    hit = _external_status_cache.get(slug)
    if hit is not None and now - hit[0] < _EXTERNAL_STATUS_TTL:
        return hit[1]

    from learning_agent.config import PROJECT_ROOT

    path = PROJECT_ROOT / "agents" / "projects" / slug / "completion-criteria.yaml"
    if not path.is_file():
        _external_status_cache[slug] = (now, None)
        return None
    from learning_agent.core import agent_external_completion

    result = agent_external_completion.assess_external_completion(slug)
    _external_status_cache[slug] = (now, result)
    return result


def _finance_l6_operational_checklist(slug: str) -> dict[str, Any]:
    """Checklist operacional L6 finance-lead — alinhado ao currículo (não escala L5 genérica)."""
    if slug != "finance-lead":
        return {"skipped": True}
    from learning_agent.core import agent_model_parity

    quiz = _quiz_mastery(slug, latest_per_item=True)
    proof_ok = _recent_proof_gate_ok()
    playbook_ok = _playbook_evolved(slug)
    row = agent_model_parity.get_agent_parity(slug)
    composite = float(row.get("composite_score") or 0)
    dims = row.get("dimensions") or {}
    reasoning = dims.get("reasoning") if isinstance(dims.get("reasoning"), dict) else {}
    reasoning_score = float(reasoning.get("score") or 0)

    checks = {
        "parity_score_80": {
            "met": composite >= 80,
            "detail": f"composite {composite}% (meta 80)",
        },
        "reasoning_80": {
            "met": reasoning.get("met", False) or reasoning_score >= 80,
            "detail": f"reasoning {reasoning_score}% (meta 80)",
        },
        "quiz_mastery_85": {
            "met": quiz["pct"] >= 85,
            "detail": f"{quiz['pct']}% ({quiz['correct']}/{quiz['attempts']}) meta 85",
        },
        "proof_gate_green": {
            "met": proof_ok,
            "detail": "proof_gate / debug_sweep verde",
        },
        "playbook_l6_autonomy": {
            "met": playbook_ok,
            "detail": "Práticas autônomas (decisão paper) no playbook",
        },
        "zero_gaps": {
            "met": _base_metrics(slug)["gap_count"] <= 0,
            "detail": f"{_base_metrics(slug)['gap_count']} lacunas",
        },
    }
    missing = [k for k, c in checks.items() if not c["met"]]
    return {
        "label": "L6 operacional (finance-lead)",
        "eligible": not missing,
        "checks": checks,
        "missing": missing,
        "quiz": quiz,
    }


def _finance_l6_specialist_status(slug: str) -> dict[str, Any]:
    """Finance-lead L6 — extensões F6–F9 + currículo L6 + Prove externo."""
    if slug != "finance-lead":
        return {"met": False, "skipped": True}
    from learning_agent.core import agent_curriculum, agent_external_completion

    ext = agent_external_completion.assess_external_completion(slug)
    cur_level = agent_curriculum.get_stored_curriculum_level(slug)
    extension_ids = {"F6", "F7", "F8", "F9"}
    criteria = ext.get("criteria") or []
    ext_pass = sum(1 for c in criteria if c.get("id") in extension_ids and c.get("passed"))
    total_ext = sum(1 for c in criteria if c.get("id") in extension_ids)
    met = (
        cur_level >= 6
        and ext.get("external_ready")
        and ext_pass >= total_ext
        and total_ext >= 4
    )
    return {
        "met": met,
        "curriculum_level": cur_level,
        "extensions_passed": ext_pass,
        "extensions_total": total_ext,
        "external_pass": f"{ext.get('passed_count', 0)}/{ext.get('total', 9)}",
        "missing": [] if met else [
            x
            for x in (
                "curriculum_l6" if cur_level < 6 else "",
                "prove_externo" if not ext.get("external_ready") else "",
                "extensoes_l6" if ext_pass < total_ext else "",
            )
            if x
        ],
    }


def _level_6_status(slug: str) -> dict[str, Any]:
    """Paridade cognitiva L6 — integrada à escala operacional."""
    from learning_agent.config import MODEL_PARITY_STRICT_MIN_SCORE
    from learning_agent.core import agent_model_parity

    row = agent_model_parity.get_agent_parity(slug)
    assessed = bool(row.get("assessed") and row.get("composite_score") is not None)
    composite = float(row.get("composite_score") or 0)
    parity_met = bool(row.get("parity_met") or row.get("level_6_eligible"))
    dims = row.get("dimensions") or {}
    weak_dims = [
        k for k, v in dims.items() if isinstance(v, dict) and not v.get("met", True)
    ]

    finance_l6 = _finance_l6_specialist_status(slug)
    parity_eligible = parity_met and assessed
    specialist_eligible = bool(finance_l6.get("met"))

    return {
        "eligible": parity_eligible or specialist_eligible,
        "assessed": assessed or specialist_eligible,
        "parity_met": parity_met,
        "finance_l6_specialist": specialist_eligible,
        "finance_l6_detail": finance_l6,
        "composite_score": composite if assessed else None,
        "min_score": MODEL_PARITY_STRICT_MIN_SCORE,
        "dimensions": dims,
        "weak_dimensions": weak_dims,
        "missing": []
        if parity_eligible or specialist_eligible
        else (
            finance_l6.get("missing") or ["strict_parity_assessment"]
            if not assessed
            else weak_dims
        ),
    }


def _level_5_checklist(agent: str, metrics: dict[str, Any]) -> dict[str, Any]:
    quiz = _quiz_mastery(agent)
    proof_ok = _recent_proof_gate_ok()
    sprint_ok = _has_verified_sprint(agent)
    playbook_ok = _playbook_evolved(agent)

    checks = {
        "base_level_4": {
            "met": _level_from_base(metrics["base_score"], metrics) >= 4,
            "detail": f"score base {metrics['base_score']}, gaps {metrics['gap_count']}",
        },
        "quiz_mastery_80": {
            "met": quiz["met"],
            "detail": f"{quiz['pct']}% ({quiz['correct']}/{quiz['attempts']} tentativas)",
        },
        "proof_gate_green": {
            "met": proof_ok,
            "detail": "proof_gate / debug_sweep verde",
        },
        "verified_micro_sprint": {
            "met": sprint_ok,
            "detail": "artefato micro-sprint com prova",
        },
        "playbook_evolved": {
            "met": playbook_ok,
            "detail": "seção Práticas autônomas no playbook",
        },
        "min_closures": {
            "met": metrics["learning_closures"] >= LEVEL_5_CRITERIA["min_closures"],
            "detail": f"{metrics['learning_closures']}/{LEVEL_5_CRITERIA['min_closures']}",
        },
        "min_elevations": {
            "met": metrics["elevations"] >= LEVEL_5_CRITERIA["min_elevations"],
            "detail": f"{metrics['elevations']}/{LEVEL_5_CRITERIA['min_elevations']}",
        },
        "min_insights": {
            "met": metrics["insights_shared"] >= LEVEL_5_CRITERIA["min_insights"],
            "detail": f"{metrics['insights_shared']}/{LEVEL_5_CRITERIA['min_insights']}",
        },
        "zero_gaps": {
            "met": metrics["gap_count"] <= LEVEL_5_CRITERIA["max_gaps"],
            "detail": f"{metrics['gap_count']} lacunas",
        },
    }
    all_met = all(c["met"] for c in checks.values())
    missing = [k for k, c in checks.items() if not c["met"]]
    return {
        "eligible": all_met,
        "checks": checks,
        "missing": missing,
        "quiz": quiz,
        "proof_gate_ok": proof_ok,
        "verified_sprint": sprint_ok,
        "playbook_evolved": playbook_ok,
    }


def compute_agent_capability(agent: str, *, run_proofs: bool = False) -> dict[str, Any]:
    """Calcula nível 1–6 (L6 = paridade cognitiva strict integrada)."""
    global _capability_depth
    slug = agent.strip().lower().replace("_", "-")
    _capability_depth += 1
    try:
        return _compute_agent_capability_impl(slug, run_proofs=run_proofs)
    finally:
        _capability_depth -= 1


def _compute_agent_capability_impl(slug: str, *, run_proofs: bool = False) -> dict[str, Any]:
    metrics = _base_metrics(slug)
    manifest = metrics.pop("manifest")
    gaps = metrics.pop("gaps")

    base_level = _level_from_base(metrics["base_score"], metrics)
    l5 = _level_5_checklist(slug, metrics)
    l6 = _level_6_status(slug)

    if run_proofs and not l5["proof_gate_ok"]:
        suite = proofs.run_full_proof_suite()
        l5["proof_gate_ok"] = bool(suite.get("all_passed"))
        l5["checks"]["proof_gate_green"]["met"] = l5["proof_gate_ok"]
        l5["eligible"] = all(c["met"] for c in l5["checks"].values())
        l5["missing"] = [k for k, c in l5["checks"].items() if not c["met"]]

    if l6["eligible"]:
        level = 6
    elif l5["eligible"]:
        level = 5
    else:
        level = base_level

    external = _external_completion_status(slug)
    if external and level >= 6 and not external.get("external_ready"):
        level = min(level, 5)
        l6 = {**l6, "eligible": False, "missing": [*l6.get("missing", []), "external_completion"]}

    final_score = metrics["base_score"]
    if level == 6 and l6.get("composite_score") is not None:
        final_score = max(final_score, float(l6["composite_score"]))
    elif level == 5:
        final_score = min(100.0, metrics["base_score"] + 15.0)

    missing = l6["missing"] if level < 6 else []
    if slug == "finance-lead" and level >= 6:
        l6_op = _finance_l6_operational_checklist(slug)
        l6 = {**l6, "operational_checklist": l6_op}
        missing = l6_op.get("missing") or []
    elif level < 6 and level >= 5:
        missing = l6["missing"] or l5["missing"]
    elif level < 5:
        missing = l5["missing"]

    next_actions = _suggest_level_up_actions(slug, level, missing)

    return {
        "success": True,
        "agent": slug,
        "display_name": manifest.get("display_name", slug),
        "archetype": manifest.get("archetype", ""),
        "level": level,
        "level_label": CAPABILITY_SCALE[level]["label"],
        "level_summary": CAPABILITY_SCALE[level]["summary"],
        "score": round(final_score, 1),
        "base_level": base_level,
        "gaps": gap_n if (gap_n := metrics["gap_count"]) else 0,
        "top_gaps": [g.get("topic", "")[:50] for g in gaps.get("gaps", [])[:3]],
        "metrics": metrics,
        "level_5": l5,
        "level_6": l6,
        "level_6_eligible": l6["eligible"],
        "external_completion": external,
        "next_actions": next_actions,
    }


def _suggest_level_up_actions(agent: str, level: int, missing: list[str]) -> list[str]:
    if level >= 6:
        return ["Manter L6: revisão spaced + model_parity_assessment periódico"]

    if level >= 5:
        actions = ["model_parity_assessment", "agent_study_session"]
        for key in missing:
            if key in ("decision", "reasoning", "knowledge"):
                actions.append("agent_study_session")
        return actions[:5]

    actions: list[str] = []
    mapping = {
        "quiz_mastery_80": "spaced_review",
        "proof_gate_green": "debug_sweep",
        "verified_micro_sprint": "real_code_sprint",
        "playbook_evolved": "evolve_playbook",
        "min_closures": "curriculum_milestone",
        "min_elevations": "weak_area_drill",
        "min_insights": "mentor_session",
        "zero_gaps": "research_gaps",
        "base_level_4": "ide_improvement_sprint",
        "strict_parity_assessment": "model_parity_assessment",
    }
    for key in missing:
        if key in mapping:
            actions.append(mapping[key])
    return actions[:5] or ["collab_dev_sprint", "code_walk"]


def assess_ecosystem(*, agents: list[str] | None = None) -> dict[str, Any]:
    global _proof_cache
    _proof_cache = None

    names = agents or CORE_AGENTS
    results = [compute_agent_capability(n) for n in names]
    results.sort(key=lambda x: (-x["level"], -x["score"]))

    level_counts = {i: 0 for i in range(1, 7)}
    for r in results:
        level_counts[r["level"]] = level_counts.get(r["level"], 0) + 1

    lowest = min(results, key=lambda x: (x["level"], x["score"]))
    specialists_l5 = [r["agent"] for r in results if r["level"] >= 5]
    specialists_l6 = [r["agent"] for r in results if r["level"] >= 6]

    report = {
        "success": True,
        "assessed_at": _utcnow(),
        "agents": results,
        "summary": {
            "total": len(results),
            "specialists": len(specialists_l5),
            "specialists_l6": len(specialists_l6),
            "specialist_names": specialists_l5,
            "specialist_l6_names": specialists_l6,
            "lowest_agent": lowest["agent"],
            "lowest_level": lowest["level"],
            "level_counts": level_counts,
        },
        "scale": CAPABILITY_SCALE,
        "level_5_criteria": LEVEL_5_CRITERIA,
        "level_6_note": "Nível 6 = paridade cognitiva strict (model_parity.json)",
        "recommended_increments": RECOMMENDED_INCREMENTS,
    }

    _persist_state(report)
    return report


def _persist_state(report: dict[str, Any]) -> None:
    CAPABILITY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    slim = {
        "assessed_at": report["assessed_at"],
        "agents": [
            {
                "agent": a["agent"],
                "level": a["level"],
                "score": a["score"],
                "missing_l5": a.get("level_5", {}).get("missing", []),
            }
            for a in report["agents"]
        ],
        "summary": report["summary"],
    }
    with CAPABILITY_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)


def get_lowest_capability_agent() -> str:
    report = assess_ecosystem()
    return str(report["summary"]["lowest_agent"])


def pick_level_up_action(cycle: int) -> str | None:
    """Sugere ação focada no agente mais atrasado (a cada 4 ciclos)."""
    if cycle % 4 != 0:
        return None
    report = assess_ecosystem()
    lowest = report["summary"]["lowest_agent"]
    agent_report = next(a for a in report["agents"] if a["agent"] == lowest)
    actions = agent_report.get("next_actions", [])
    if not actions:
        return None
    first = actions[0]
    action_map = {
        "peer_quiz": "peer_quiz",
        "spaced_review": "spaced_review",
        "debug_sweep": "debug_sweep",
        "execute_micro_sprint": "execute_micro_sprint",
        "real_code_sprint": "real_code_sprint",
        "evolve_playbook": "evolve_playbook",
        "weak_area_drill": "weak_area_drill",
        "research_gaps": "research_gaps",
        "mentor_session": "mentor_session",
        "ide_improvement_sprint": "ide_improvement_sprint",
        "curriculum_milestone": "curriculum_milestone",
        "peer_question": "peer_question",
        "distill_for_peers": "distill_for_peers",
    }
    return action_map.get(first, "peer_quiz")
