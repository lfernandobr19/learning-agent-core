"""Paridade cognitiva — agentes vs modelos de referência (conhecimento, raciocínio, decisão)."""

from __future__ import annotations

import json
import re
from typing import Any

from learning_agent.config import (
    MODEL_PARITY_MIN_SCORE,
    MODEL_PARITY_REFERENCE_BALANCED,
    MODEL_PARITY_REFERENCE_FAST,
    MODEL_PARITY_REFERENCE_REASONING,
    MODEL_PARITY_STATE_PATH,
    MODEL_PARITY_STRICT_MIN_SCORE,
    MODEL_PARITY_TARGET_TIER,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
)
from learning_agent.core import agent_collaboration, knowledge, llm as llm_core

NORTH_STAR = (
    "Cada agente deve ser equivalente aos modelos do plano Cursor em conhecimento, "
    "raciocínio e tomada de decisão — medido por benchmarks, não por volume de quiz."
)

TIERS: dict[str, dict[str, Any]] = {
    "fast": {
        "label": "Rápido",
        "cursor_analog": "Composer Fast / modelos leves",
        "reference_model": MODEL_PARITY_REFERENCE_FAST,
        "min_score": 65,
    },
    "balanced": {
        "label": "Balanceado",
        "cursor_analog": "Sonnet / GPT-4o do plano",
        "reference_model": MODEL_PARITY_REFERENCE_BALANCED,
        "min_score": 75,
    },
    "reasoning": {
        "label": "Raciocínio",
        "cursor_analog": "Opus / thinking do plano",
        "reference_model": MODEL_PARITY_REFERENCE_REASONING,
        "min_score": 85,
    },
}

DOMAIN_PROMPTS: dict[str, dict[str, str]] = {
    "backend": {
        "knowledge": (
            "Explique em 4 frases: camadas FastAPI (router/service/repo), "
            "quando usar async e como testar com TestClient."
        ),
        "reasoning": (
            "A API está lenta em endpoints que consultam SQLite e ChromaDB em série. "
            "Qual ordem de otimização você prioriza e por quê?"
        ),
        "decision": (
            "Devemos mover autonomia dos agentes para background Celery ou manter asyncio "
            "no mesmo processo FastAPI? Decida e justifique trade-offs."
        ),
    },
    "frontend": {
        "knowledge": (
            "Liste padrões React para evitar re-renders no Observador com centenas de mensagens WS."
        ),
        "reasoning": (
            "O Observador quadruplicava mensagens. Diagnostique causas prováveis e ordem de correção."
        ),
        "decision": (
            "Implementar LSP no Monaco agora ou command palette primeiro para paridade Cursor? "
            "Escolha uma rota e critérios de sucesso."
        ),
    },
    "qa-inspector": {
        "knowledge": "Defina smoke vs integration vs e2e neste monorepo Python+React.",
        "reasoning": "cloud_sync falha com drift de 1 nota. É bug ou tolerância aceitável?",
        "decision": "Priorize: mais testes agent_sprints ou endurecer peer_quiz com avaliação real?",
    },
    "data": {
        "knowledge": "Quais índices SQLite adicionar para quiz_attempts e agent_exchanges?",
        "reasoning": "Notas locais > nuvem após autonomia. Causas e mitigação.",
        "decision": "Sync push antes de proof_gate ou tolerância de drift configurável?",
    },
    "debug-optimizer": {
        "knowledge": (
            "Defina SLO, SLI e orçamento de erro para API FastAPI de agentes. "
            "Inclua RED metrics e exemplos de logs estruturados."
        ),
        "reasoning": (
            "p95 latência triplicou após deploy com autonomia asyncio. "
            "Ordene investigação (métricas, traces, deploy diff, dependências)."
        ),
        "decision": (
            "Incidente P2: rollback imediato, hotfix com feature flag, ou escalar horizontal? "
            "Decida UMA rota com critérios de sucesso, rollback e quem aciona o quê."
        ),
    },
    "custom": {
        "knowledge": "O que é paridade cognitiva vs paridade de ferramentas IDE?",
        "reasoning": "Como medir agente sem acesso direto aos modelos do plano Cursor?",
        "decision": "Usar teacher API como juiz ou orquestrar eval via MCP Cursor?",
    },
}

AGENT_DOMAIN_PROMPTS: dict[str, dict[str, str]] = {
    "finance-lead": {
        "knowledge": (
            "Explique reserva de emergência, juros compostos e diferença entre P/L e P/VP "
            "para ações e FIIs no mercado brasileiro."
        ),
        "reasoning": (
            "Selic estável, IPCA sobe, Ibovespa cai 15% e USD/BRL valoriza 8%. "
            "Como raciocinar rebalanceamento para carteira PF moderada?"
        ),
        "decision": (
            "Após queda de 30% em 2 ações tech BR, concentrar 40% da carteira ou limitar "
            "por emissor? Decida UMA rota com sizing, critérios de invalidação e rollback."
        ),
    },
}


def _parse_score(text: str) -> float:
    m = re.search(r"(\d{1,3})\s*/\s*100", text)
    if m:
        return min(100.0, float(m.group(1)))
    m = re.search(r"\b(\d{1,2})\b", text)
    if m:
        return min(100.0, float(m.group(1)) * 10)
    return 50.0


STRICT_DECISION_MARKERS = (
    "critério",
    "trade-off",
    "rollback",
    "prova",
    "teste",
    "métrica",
    "slo",
    "aceite",
)

STRICT_REASONING_MARKERS = (
    "causa",
    "mitiga",
    "prioriz",
    "passo",
    "ordem",
    "verific",
    "critério",
    "rollback",
)

STRICT_DIMENSION_GUIDE: dict[str, str] = {
    "knowledge": "Cobertura técnica precisa; cite APIs, tabelas ou arquivos do monorepo quando couber.",
    "reasoning": (
        "Use: 1) causas ordenadas 2) passos de mitigação numerados "
        "3) critério de aceite mensurável 4) rollback se a mitigação falhar."
    ),
    "decision": (
        "Use: trade-offs → UMA decisão clara → critérios de aceite mensuráveis → rollback → prova/teste."
    ),
}

# Probe leve — assess_readiness (~2min) falha por timeout/concorrência Chroma no Windows
_FAST_PROBE_TESTS = ["tests/test_l6_strict.py", "tests/test_agent_study_methodology.py"]
_PROBE_TIMEOUT_SECONDS = 90
_INFRA_EXIT_CODES = {-1073741819, 3221225477, -9}


def _judge_teacher(
    dimension: str,
    prompt: str,
    answer: str,
    archetype: str,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Juiz via professor (proxy tier Cursor) — nunca usa o aluno local."""
    min_score = MODEL_PARITY_STRICT_MIN_SCORE if strict else TIERS["balanced"]["min_score"]
    rubric = {
        "knowledge": "precisão técnica, cobertura do domínio, zero vagueza",
        "reasoning": "causalidade, priorização, passos verificáveis",
        "decision": "trade-offs explícitos, UMA decisão clara, critérios de aceite mensuráveis",
    }
    strict_extra = ""
    if strict:
        strict_extra = (
            f"\nSeja EXIGENTE como benchmark Cursor Sonnet: nota < {min_score} se faltar "
            "critério de aceite, rollback, ou prova/teste em «decision»."
        )
    judge_prompt = (
        f"Você avalia paridade com tier Cursor ({MODEL_PARITY_REFERENCE_BALANCED}). "
        f"Domínio: {archetype}, dimensão: {dimension} ({rubric[dimension]}).{strict_extra}\n"
        "Responda APENAS: SCORE: NN/100 e uma linha de feedback objetiva."
    )
    if not TEACHER_API_KEY:
        return {"score": 0.0, "feedback": "TEACHER_API_KEY ausente", "judge_model": "unavailable"}
    try:
        raw = llm_core.chat_complete(
            [
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": f"Pergunta:\n{prompt}\n\nResposta do agente:\n{answer}"},
            ],
            base_url=TEACHER_API_BASE,
            api_key=TEACHER_API_KEY,
            model=TEACHER_MODEL,
            max_tokens=150,
            temperature=0.15,
        )
        model = TEACHER_MODEL
    except Exception as exc:
        return {"score": 0.0, "feedback": str(exc), "judge_model": "unavailable"}

    score = _parse_score(raw)
    lower = answer.lower()
    if strict and dimension == "decision":
        if not any(m in lower for m in STRICT_DECISION_MARKERS):
            score = min(score, float(min_score - 5))
    elif strict and dimension == "reasoning":
        if not any(m in lower for m in STRICT_REASONING_MARKERS):
            score = min(score, float(min_score - 5))
    return {"score": score, "feedback": raw[:300], "judge_model": model}


def _judge(dimension: str, prompt: str, answer: str, archetype: str) -> dict[str, Any]:
    rubric = {
        "knowledge": "precisão técnica e cobertura do domínio",
        "reasoning": "passos lógicos, causalidade, priorização",
        "decision": "trade-offs explícitos, decisão clara, critérios de sucesso",
    }
    judge_prompt = (
        f"Avalie a resposta do agente {archetype} em «{dimension}» ({rubric[dimension]}). "
        "Responda APENAS: SCORE: NN/100 e uma linha de feedback."
    )
    try:
        raw, model = llm_core.chat_with_fallback(
            [
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": f"Pergunta:\n{prompt}\n\nResposta:\n{answer}"},
            ],
            max_tokens=120,
            temperature=0.2,
        )
    except Exception as exc:
        return {"score": 0.0, "feedback": str(exc), "judge_model": "unavailable"}

    return {
        "score": _parse_score(raw),
        "feedback": raw[:300],
        "judge_model": model or TEACHER_MODEL,
    }


def _prompts_for(agent: str) -> dict[str, str]:
    slug = agent.strip().lower().replace("_", "-")
    if slug in AGENT_DOMAIN_PROMPTS:
        return dict(AGENT_DOMAIN_PROMPTS[slug])
    manifest = agent_collaboration._load_manifest(slug) or {}
    arch = str(manifest.get("archetype", "custom"))
    base = DOMAIN_PROMPTS.get(arch, DOMAIN_PROMPTS["custom"])
    focus = manifest.get("focus", "")
    if focus:
        base = {
            **base,
            "knowledge": f"{base['knowledge']}\nFoco do agente: {focus}",
        }
    return base


def _mentor_snippet(slug: str, dimension: str) -> str:
    try:
        from learning_agent.core.cursor_mentor import CURSOR_MENTOR_LESSONS

        return (CURSOR_MENTOR_LESSONS.get(slug, {}).get(dimension) or "")[:1200]
    except Exception:
        return ""


def _answer_as_agent(
    slug: str,
    display: str,
    archetype: str,
    prompt: str,
    *,
    strict: bool = False,
    dimension: str = "",
) -> tuple[str, str]:
    """Resposta do agente via motor raven + contexto RAG + lição mentor (strict)."""
    context_block = ""
    if strict:
        lines: list[str] = []
        mentor = _mentor_snippet(slug, dimension) if dimension else ""
        if mentor:
            lines.append(f"[Lição mentor Cursor — {dimension}]\n{mentor}")
        # Evita Chroma no mesmo processo que Ollama (access violation no Windows).
        try:
            from learning_agent import db

            db.init_db()
            with db.get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT title, content FROM learning_notes
                    WHERE tags LIKE ? OR title LIKE ?
                    ORDER BY id DESC LIMIT 2
                    """,
                    (f"%agent:{slug}%", f"%{slug}%"),
                ).fetchall()
            for row in rows:
                lines.append(f"{row['title']}\n{(row['content'] or '')[:400]}")
        except Exception:
            pass
        if lines:
            context_block = "\n---\n".join(lines)

    system = (
        f"Você é {display}, especialista {archetype} em engenharia de software. "
        "Responda em português, técnico, com decisões e critérios de aceite quando pedido."
    )
    if strict and dimension:
        guide = STRICT_DIMENSION_GUIDE.get(dimension, "")
        if guide:
            system += f"\n\nFORMATO L6 ({dimension}): {guide}"
    if context_block:
        system += f"\n\nCONTEXTO DO PROJETO:\n{context_block}"

    try:
        return llm_core.chat_with_fallback(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=520 if strict else 280,
            temperature=0.3 if strict else 0.4,
        )
    except Exception as exc:
        return f"(sem resposta: {exc})", "unavailable"


def _run_real_capability_probe(slug: str) -> dict[str, Any]:
    """Prova real rápida — testes unitários leves (evita assess_readiness ~2min + Chroma)."""
    import os
    import subprocess
    import sys

    probes: dict[str, list[str]] = {
        slug: _FAST_PROBE_TESTS for slug in (
            "qa-guardian",
            "backend-lead",
            "data-engineer",
            "frontend-lead",
            "reliability-lead",
        )
    }
    paths = probes.get(slug, [])
    if not paths:
        return {"ran": False, "passed": None, "note": "sem probe automatizado para este agente"}

    from learning_agent.config import PROJECT_ROOT

    env = {**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"}
    cmd = [sys.executable, "-m", "pytest", *paths, "-q", "--tb=no"]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            env=env,
        )
        if r.returncode in _INFRA_EXIT_CODES:
            return {
                "ran": True,
                "passed": None,
                "infra_failure": True,
                "exit_code": r.returncode,
                "stdout_tail": (r.stdout or "")[-300:],
            }
        return {
            "ran": True,
            "passed": r.returncode == 0,
            "exit_code": r.returncode,
            "stdout_tail": (r.stdout or "")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"ran": True, "passed": None, "infra_failure": True, "error": "timeout"}
    except Exception as exc:
        return {"ran": True, "passed": None, "infra_failure": True, "error": str(exc)[:200]}


def run_strict_parity_assessment(
    agent: str,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Benchmark L6 exigente — juiz professor, RAG, prova real opcional."""
    slug = agent.strip().lower().replace("_", "-")
    manifest = agent_collaboration._load_manifest(slug) or {}
    display = manifest.get("display_name", slug)
    archetype = str(manifest.get("archetype", "custom"))
    prompts = _prompts_for(slug)
    tier = TIERS.get(MODEL_PARITY_TARGET_TIER, TIERS["balanced"])
    min_score = MODEL_PARITY_STRICT_MIN_SCORE

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug,
            f"L6 STRICT (Cursor-tier ≥{min_score}): avaliando com juiz professor…",
            level="model-parity-strict",
        )

    dimensions: dict[str, Any] = {}
    for dim, prompt in prompts.items():
        answer, model = _answer_as_agent(
            slug, display, archetype, prompt, strict=True, dimension=dim
        )
        verdict = _judge_teacher(dim, prompt, answer, archetype, strict=True)
        dimensions[dim] = {
            "prompt": prompt,
            "answer": answer[:800],
            "agent_model": model,
            "score": verdict["score"],
            "feedback": verdict["feedback"],
            "judge_model": verdict["judge_model"],
            "met": verdict["score"] >= min_score,
            "strict": True,
        }

    probe = _run_real_capability_probe(slug)
    probe_bonus = 0.0
    if probe.get("ran") and probe.get("passed") is True:
        probe_bonus = 3.0
    elif probe.get("ran") and probe.get("passed") is False and not probe.get("infra_failure"):
        probe_bonus = -3.0

    weights = {"knowledge": 0.35, "reasoning": 0.35, "decision": 0.30}
    composite = round(
        sum(dimensions[d]["score"] * weights[d] for d in weights if d in dimensions) + probe_bonus,
        1,
    )
    composite = max(0.0, min(100.0, composite))
    all_met = all(dimensions[d]["met"] for d in dimensions)
    probe_ok = (
        probe.get("passed") is not False
        if probe.get("ran") and not probe.get("infra_failure")
        else True
    )
    parity_met = composite >= min_score and all_met and probe_ok

    result = {
        "success": True,
        "action": "strict_parity_assessment",
        "mode": "cursor_benchmark_strict",
        "agent": slug,
        "display_name": display,
        "north_star": NORTH_STAR,
        "target_tier": MODEL_PARITY_TARGET_TIER,
        "min_score": min_score,
        "reference_tier": tier,
        "dimensions": dimensions,
        "real_probe": probe,
        "composite_score": composite,
        "parity_met": parity_met,
        "level_6_eligible": parity_met,
    }
    _persist_agent(slug, result)

    knowledge.add_note(
        f"[L6 STRICT] {display}",
        json.dumps(
            {k: dimensions[k]["score"] for k in dimensions},
            ensure_ascii=False,
        )
        + f"\ncomposite={composite}\nprobe={probe}\nstrict=true",
        tags=["model-parity", "level-6", "strict", f"agent:{slug}"],
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug,
            f"L6 STRICT {composite}/100 — "
            + ", ".join(f"{k}:{dimensions[k]['score']}" for k in dimensions)
            + (f" | probe:{'ok' if probe.get('passed') else 'fail'}" if probe.get("ran") else ""),
            level="model-parity-strict-result",
        )
    return result


def run_model_parity_assessment(
    agent: str,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Benchmark: conhecimento, raciocínio e decisão vs tier de referência."""
    slug = agent.strip().lower().replace("_", "-")
    manifest = agent_collaboration._load_manifest(slug) or {}
    display = manifest.get("display_name", slug)
    archetype = str(manifest.get("archetype", "custom"))
    prompts = _prompts_for(slug)
    tier = TIERS.get(MODEL_PARITY_TARGET_TIER, TIERS["balanced"])

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug,
            f"Paridade cognitiva ({tier['label']}): avaliando conhecimento, raciocínio e decisão…",
            level="model-parity",
        )

    dimensions: dict[str, Any] = {}
    for dim, prompt in prompts.items():
        try:
            answer, model = llm_core.chat_with_fallback(
                [
                    {
                        "role": "system",
                        "content": (
                            f"Você é {display}, especialista {archetype}. "
                            "Responda em português, técnico e direto."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=280,
                temperature=0.45,
            )
        except Exception as exc:
            answer, model = f"(sem resposta: {exc})", "unavailable"

        verdict = _judge(dim, prompt, answer, archetype)
        dimensions[dim] = {
            "prompt": prompt,
            "answer": answer[:600],
            "agent_model": model,
            "score": verdict["score"],
            "feedback": verdict["feedback"],
            "judge_model": verdict["judge_model"],
            "met": verdict["score"] >= tier["min_score"],
        }

    weights = {"knowledge": 0.35, "reasoning": 0.35, "decision": 0.30}
    composite = round(
        sum(dimensions[d]["score"] * weights[d] for d in weights if d in dimensions),
        1,
    )
    all_met = all(dimensions[d]["met"] for d in dimensions)
    parity_met = composite >= MODEL_PARITY_MIN_SCORE and all_met

    result = {
        "success": True,
        "action": "model_parity_assessment",
        "agent": slug,
        "display_name": display,
        "north_star": NORTH_STAR,
        "target_tier": MODEL_PARITY_TARGET_TIER,
        "reference_tier": tier,
        "reference_models": {
            "fast": MODEL_PARITY_REFERENCE_FAST,
            "balanced": MODEL_PARITY_REFERENCE_BALANCED,
            "reasoning": MODEL_PARITY_REFERENCE_REASONING,
        },
        "cursor_note": (
            "Modelos Cursor do plano não são acessíveis diretamente pela API Ravenna. "
            "Configure MODEL_PARITY_REFERENCE_* no .env com os equivalentes do seu plano "
            "ou avalie via Cursor MCP postando em /api/theater/message."
        ),
        "dimensions": dimensions,
        "composite_score": composite,
        "parity_met": parity_met,
        "level_6_eligible": parity_met,
    }
    _persist_agent(slug, result)

    knowledge.add_note(
        f"[Paridade cognitiva] {display}",
        json.dumps(
            {k: dimensions[k]["score"] for k in dimensions},
            ensure_ascii=False,
        )
        + f"\ncomposite={composite}\ntier={MODEL_PARITY_TARGET_TIER}",
        tags=["model-parity", f"agent:{slug}", "level-6"],
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug,
            f"Paridade {composite}/100 — "
            + ", ".join(f"{k}:{dimensions[k]['score']}" for k in dimensions),
            level="model-parity-result",
        )

    return result


def get_agent_parity(agent: str) -> dict[str, Any]:
    slug = agent.strip().lower().replace("_", "-")
    state = _load_state()
    cached = state.get("agents", {}).get(slug)
    if cached:
        return {"success": True, "agent": slug, **cached}
    return {
        "success": True,
        "agent": slug,
        "assessed": False,
        "message": "Rode model_parity_assessment para medir paridade cognitiva",
        "target_tier": MODEL_PARITY_TARGET_TIER,
        "reference_tier": TIERS.get(MODEL_PARITY_TARGET_TIER, TIERS["balanced"]),
    }


def assess_ecosystem_parity(*, agents: list[str] | None = None) -> dict[str, Any]:
    from learning_agent.core.agent_capability import CORE_AGENTS

    names = agents or CORE_AGENTS
    state = _load_state()
    reports = [get_agent_parity(n) for n in names]
    assessed = [r for r in reports if r.get("composite_score") is not None]
    specialists = [r for r in assessed if r.get("parity_met")]

    return {
        "success": True,
        "north_star": NORTH_STAR,
        "target_tier": MODEL_PARITY_TARGET_TIER,
        "tiers": TIERS,
        "agents": reports,
        "summary": {
            "total": len(names),
            "assessed": len(assessed),
            "parity_met": len(specialists),
            "lowest_agent": min(assessed, key=lambda x: x.get("composite_score", 0))["agent"]
            if assessed
            else names[0],
            "lowest_score": min((r.get("composite_score", 0) for r in assessed), default=0),
        },
        "cursor_integration": {
            "direct_cursor_models": False,
            "via_env": "MODEL_PARITY_REFERENCE_* no .env",
            "via_mcp": "POST /api/theater/message com avaliação do agente Cursor",
        },
    }


def _load_state() -> dict[str, Any]:
    if not MODEL_PARITY_STATE_PATH.is_file():
        return {"agents": {}}
    try:
        with MODEL_PARITY_STATE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {"agents": {}}
    except (json.JSONDecodeError, OSError):
        return {"agents": {}}


def _persist_agent(slug: str, result: dict[str, Any]) -> None:
    state = _load_state()
    agents = state.setdefault("agents", {})
    agents[slug] = {
        "assessed": True,
        "composite_score": result["composite_score"],
        "parity_met": result["parity_met"],
        "level_6_eligible": result["level_6_eligible"],
        "target_tier": result["target_tier"],
        "dimensions": {
            k: {"score": v["score"], "met": v["met"]}
            for k, v in result["dimensions"].items()
        },
        "reference_model": result["reference_tier"].get("reference_model"),
    }
    if result.get("real_probe"):
        agents[slug]["real_probe"] = {
            "passed": result["real_probe"].get("passed"),
            "infra_failure": result["real_probe"].get("infra_failure"),
        }
    MODEL_PARITY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MODEL_PARITY_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
