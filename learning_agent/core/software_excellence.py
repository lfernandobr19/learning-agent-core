"""Objetivo norte — fábrica de software de excelência sob demanda.

A Raven Eco IDE é aula prática; este módulo define quando o ecossistema está
pronto para criar software de alto nível em qualquer domínio.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from learning_agent import db
from learning_agent.config import (
    DATA_DIR,
    PROJECT_ROOT,
    SOFTWARE_EXCELLENCE_STATE_PATH,
    STUDENT_FINETUNE_MODEL,
)
from learning_agent.core import agent_capability, finetune, ide_objectives

NORTH_STAR = (
    "A Ravenna estará pronta para criar software de excelência sob demanda quando o "
    "ecossistema atingir maturidade cognitiva, cérebro local treinado e provas verdes. "
    "A Raven Eco IDE é apenas aula prática — não é o produto final."
)

COMPLETION_RULES = {
    "factory_pillar_min_pct": 100.0,
    "all_must_objectives_met": True,
    "ide_practice_optional": True,
}

TRAINING_DIR = DATA_DIR / "training"

ProbeFn = Callable[[], bool]


def _count_distillation_pairs() -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0])


def _count_notes() -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM learning_notes").fetchone()[0])


def _count_closures() -> int:
    db.init_db()
    with db.get_connection() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM learning_notes WHERE tags LIKE '%learning-closure%'"
            ).fetchone()[0]
        )


def _training_examples() -> int:
    export = finetune.export_training_data(min_pairs=0)
    return int(export.get("examples", 0))


_ECOSYSTEM_CACHE: dict[str, Any] = {"at": 0.0, "report": None}
_ECOSYSTEM_CACHE_TTL = 300.0  # segundos


def _assess_ecosystem_cached() -> dict[str, Any]:
    """assess_ecosystem() é caro (~8s: 5 agentes × compute_agent_capability).

    Cache de curta duração reutiliza o relatório dentro de um mesmo
    assess_excellence() e entre chamadas próximas do painel.
    """
    import time

    now = time.monotonic()
    if (
        _ECOSYSTEM_CACHE["report"] is not None
        and now - float(_ECOSYSTEM_CACHE["at"]) < _ECOSYSTEM_CACHE_TTL
    ):
        return _ECOSYSTEM_CACHE["report"]
    report = agent_capability.assess_ecosystem()
    _ECOSYSTEM_CACHE["at"] = now
    _ECOSYSTEM_CACHE["report"] = report
    return report


def _all_core_agents_l5() -> bool:
    report = _assess_ecosystem_cached()
    agents = report.get("agents", [])
    core = [a for a in agents if a.get("agent") in agent_capability.CORE_AGENTS]
    return bool(core) and all(a.get("level", 1) >= 5 for a in core)


def _specialists_count() -> int:
    report = _assess_ecosystem_cached()
    return int(report.get("summary", {}).get("specialists", 0))


def _verified_sprints_all_core() -> bool:
    return all(agent_capability._has_verified_sprint(a) for a in agent_capability.CORE_AGENTS)


def _modelfile_exists() -> bool:
    return (TRAINING_DIR / "Modelfile").is_file()


def _training_jsonl_exists() -> bool:
    return (TRAINING_DIR / "ravenna_train.jsonl").is_file()


_OLLAMA_PROBE_CACHE: dict[str, float | bool] = {"at": 0.0, "value": False}
_OLLAMA_PROBE_TTL = 30.0  # segundos


def _ollama_has_ravenna_student() -> bool:
    """True se o modelo aluno `raven` existir no Ollama (CLI local ou API HTTP).

    Cache de curta duração (TTL) evita repetir a sonda lenta (ollama list + HTTP)
    a cada chamada do painel /api/excellence quando o modelo local está ausente.
    """
    import time

    now = time.monotonic()
    if now - float(_OLLAMA_PROBE_CACHE["at"]) < _OLLAMA_PROBE_TTL:
        return bool(_OLLAMA_PROBE_CACHE["value"])

    value = _probe_ollama_student()
    _OLLAMA_PROBE_CACHE["at"] = now
    _OLLAMA_PROBE_CACHE["value"] = value
    return value


def _probe_ollama_student() -> bool:
    name = STUDENT_FINETUNE_MODEL
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and name in (result.stdout or ""):
            return True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass

    # Probe HTTP — cobre Docker apontando para Vast/host Ollama
    import urllib.request

    bases: list[str] = []
    for env_key in ("OLLAMA_HOST", "CHAT_API_BASE", "STUDENT_API_BASE"):
        raw = (os.environ.get(env_key) or "").strip().rstrip("/")
        if not raw:
            continue
        if raw.endswith("/v1"):
            raw = raw[:-3]
        if "://" not in raw:
            raw = f"http://{raw}"
        bases.append(raw)
    bases.extend(
        [
            "http://127.0.0.1:11434",
            "http://host.docker.internal:11435",
            "http://host.docker.internal:11434",
        ]
    )
    seen: set[str] = set()
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            models = payload.get("models") or []
            for m in models:
                model_name = str(m.get("name") or m.get("model") or "")
                if model_name == name or model_name.startswith(f"{name}:"):
                    return True
        except (OSError, TimeoutError, json.JSONDecodeError, ValueError):
            continue
    return False


def _model_parity_started() -> bool:
    from learning_agent.config import MODEL_PARITY_STATE_PATH

    if not MODEL_PARITY_STATE_PATH.is_file():
        return False
    try:
        data = json.loads(MODEL_PARITY_STATE_PATH.read_text(encoding="utf-8"))
        return bool(data.get("agents") or data.get("assessed_at"))
    except (json.JSONDecodeError, OSError):
        return False


FACTORY_OBJECTIVES: list[dict[str, Any]] = [
    {
        "id": "ecosystem_l5",
        "category": "cognitive",
        "tier": "must",
        "title": "5 agentes core em L5 (Especialista)",
        "description": "Todos os leads atingem critérios de especialista",
        "owner": "ravenna",
        "action": "capability_assessment",
        "probe": _all_core_agents_l5,
    },
    {
        "id": "verified_sprints",
        "category": "cognitive",
        "tier": "must",
        "title": "Sprints verificados por agente",
        "description": "Cada core agente com sprint real ou micro-sprint comprovado",
        "owner": "qa-guardian",
        "action": "real_code_sprint",
        "probe": _verified_sprints_all_core,
    },
    {
        "id": "learning_closures",
        "category": "cognitive",
        "tier": "must",
        "title": "Fechamentos de aprendizado",
        "description": "Pelo menos 10 closures com prova",
        "owner": "backend-lead",
        "action": "learning_closure",
        "probe": lambda: _count_closures() >= 10,
    },
    {
        "id": "distillation_corpus",
        "category": "brain",
        "tier": "must",
        "title": "Corpus de destilação",
        "description": "Pares professor→aluno acumulados para treinar o cérebro",
        "owner": "data-engineer",
        "action": "consult_teacher",
        "probe": lambda: _count_distillation_pairs() >= 20,
    },
    {
        "id": "training_export",
        "category": "brain",
        "tier": "must",
        "title": "Dataset de treino exportado",
        "description": "JSONL com notas, destilação e trocas dos agentes",
        "owner": "data-engineer",
        "action": "export_training",
        "probe": lambda: _training_examples() >= 50 and _training_jsonl_exists(),
    },
    {
        "id": "modelfile_ready",
        "category": "brain",
        "tier": "must",
        "title": "Modelfile Ravenna gerado",
        "description": "Identidade + few-shots destilados prontos para Ollama",
        "owner": "data-engineer",
        "action": "brain_pipeline",
        "probe": _modelfile_exists,
    },
    {
        "id": "ravenna_student_model",
        "category": "brain",
        "tier": "must",
        "title": "Modelo raven local",
        "description": "Cérebro local criado via Ollama — sem API em runtime",
        "owner": "ravenna",
        "action": "brain_pipeline",
        "probe": _ollama_has_ravenna_student,
    },
    {
        "id": "proof_gate_green",
        "category": "delivery",
        "tier": "must",
        "title": "Proof gate verde",
        "description": "Suite de provas reais passando",
        "owner": "reliability-lead",
        "action": "proof_gate",
        "probe": agent_capability._recent_proof_gate_ok,
    },
    {
        "id": "knowledge_base",
        "category": "delivery",
        "tier": "must",
        "title": "Base de conhecimento madura",
        "description": "Memória RAG com volume suficiente para domínios variados",
        "owner": "backend-lead",
        "action": "active_learning",
        "probe": lambda: _count_notes() >= 100,
    },
    {
        "id": "model_parity_track",
        "category": "delivery",
        "tier": "must",
        "title": "Trilha de paridade cognitiva (L6)",
        "description": "Benchmarks cognitivos iniciados para elevar raciocínio",
        "owner": "ravenna",
        "action": "model_parity_assessment",
        "probe": _model_parity_started,
    },
]

PRACTICE_OBJECTIVES: list[dict[str, Any]] = [
    {
        "id": "ide_practice_active",
        "category": "practice",
        "tier": "practice",
        "title": "Aula prática — Raven Eco IDE",
        "description": "Paridade Cursor como ginásio (não bloqueia conclusão da fábrica)",
        "owner": "frontend-lead",
        "action": "ide_improvement_sprint",
        "probe": lambda: ide_objectives.assess_completion().get("summary", {}).get("cursor_parity_pct", 0) >= 40,
    },
    {
        "id": "agent_sprint_tests",
        "category": "practice",
        "tier": "practice",
        "title": "Testes de sprint por agente",
        "description": "Suíte de smoke/sprint real no repositório",
        "owner": "qa-guardian",
        "action": "real_code_sprint",
        "probe": lambda: len(list((PROJECT_ROOT / "tests" / "agent_sprints").glob("test_sprint_*.py"))) >= 5,
    },
]


def _eval_objectives(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
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


def assess_excellence() -> dict[str, Any]:
    """Avalia prontidão da fábrica de software de excelência."""
    factory_items = _eval_objectives(FACTORY_OBJECTIVES)
    practice_items = _eval_objectives(PRACTICE_OBJECTIVES)

    must = [o for o in factory_items if o.get("tier") == "must"]
    must_met = sum(1 for o in must if o["met"])
    must_total = len(must)
    factory_pct = round(100.0 * must_met / max(must_total, 1), 1)
    practice_pct = round(
        100.0 * sum(1 for o in practice_items if o["met"]) / max(len(practice_items), 1),
        1,
    )

    missing_must = [o["id"] for o in must if not o["met"]]
    next_obj = next((o for o in factory_items if not o["met"]), None)

    complete = must_met == must_total and factory_pct >= COMPLETION_RULES["factory_pillar_min_pct"]

    by_category: dict[str, list[dict[str, Any]]] = {}
    for o in factory_items:
        by_category.setdefault(o["category"], []).append(o)

    brain_status = {
        "distillation_pairs": _count_distillation_pairs(),
        "training_examples": _training_examples(),
        "modelfile": _modelfile_exists(),
        "ravenna_student": _ollama_has_ravenna_student(),
        "student_model_name": STUDENT_FINETUNE_MODEL,
    }

    result = {
        "success": True,
        "complete": complete,
        "north_star": NORTH_STAR,
        "completion_rules": COMPLETION_RULES,
        "ide_is_practice_only": True,
        "summary": {
            "factory_ready_pct": factory_pct,
            "practice_pct": practice_pct,
            "must_met": must_met,
            "must_total": must_total,
            "specialists_l5": _specialists_count(),
            "status_label": "PRONTA" if complete else "EM FORMAÇÃO",
        },
        "factory_objectives": factory_items,
        "practice_objectives": practice_items,
        "by_category": by_category,
        "missing_must": missing_must,
        "next_objective": next_obj,
        "recommended_owner": (next_obj or {}).get("owner", "ravenna"),
        "recommended_action": (next_obj or {}).get("action", "software_excellence_sprint"),
        "brain": brain_status,
        "ide_practice": ide_objectives.load_completion_snapshot(),
    }
    _persist_snapshot(result)
    return result


def get_next_objective() -> dict[str, Any]:
    report = assess_excellence()
    nxt = report.get("next_objective")
    if not nxt:
        return {
            "success": True,
            "message": "Fábrica de software pronta — ecossistema maduro",
            "complete": True,
        }
    return {
        "success": True,
        "complete": False,
        "objective": nxt,
        "owner": nxt.get("owner", "ravenna"),
        "action": nxt.get("action", "software_excellence_sprint"),
    }


DISTILLATION_BATCH_TOPICS: list[str] = [
    "Arquitetura de software em camadas para produtos sob demanda",
    "API REST resiliente com FastAPI — rotas, serviços e testes",
    "Pirâmide de testes: unit, integração e e2e em monorepos",
    "React TypeScript — padrões staff, estado e performance",
    "Observabilidade: logging estruturado, métricas e health checks",
    "CI/CD enxuto para equipes pequenas com provas verdes",
    "DDD leve: bounded contexts sem over-engineering",
    "Segurança em APIs: auth, validação e secrets",
    "PostgreSQL — modelagem, índices e migrações seguras",
    "WebSockets e tempo real em aplicações web",
    "RAG e embeddings em produção com ChromaDB",
    "Orquestração multi-agente com playbooks e provas",
    "Code review eficaz e critérios de merge",
    "Refatoração segura com testes como rede",
    "Performance frontend — Core Web Vitals e bundle budget",
    "Error handling, retries e resiliência em backends",
    "Documentação técnica viva alinhada ao código",
    "Deploy containerizado e ambientes dev/staging/prod",
    "Acessibilidade WCAG em SPAs React",
    "Knowledge distillation e fine-tune de modelos locais Ollama",
    "Entrega de software de excelência — critérios de aceite",
    "Scaffolding de novos projetos a partir de arquétipos",
]


def run_distillation_batch(
    *,
    target_pairs: int = 20,
    max_topics: int | None = None,
    broadcast_observer: bool = False,
    refresh_brain: bool = True,
) -> dict[str, Any]:
    """Destilação em massa até atingir o corpus mínimo da fábrica."""
    from learning_agent.core import agent_collaboration, distillation, knowledge

    if not distillation.is_configured():
        return {
            "success": False,
            "error": "Distillation não configurada — verifique TEACHER_* e STUDENT_* no .env",
            "status": distillation.get_status(),
        }

    before = _count_distillation_pairs()
    needed = max(0, target_pairs - before)
    if needed == 0:
        result: dict[str, Any] = {
            "success": True,
            "action": "distillation_batch",
            "message": f"Corpus já atinge {before} pares (meta {target_pairs})",
            "pairs_before": before,
            "pairs_after": before,
            "distilled": 0,
        }
        if refresh_brain:
            result["brain"] = run_brain_pipeline(dry_run=False, broadcast_observer=broadcast_observer)
        result["excellence"] = assess_excellence()["summary"]
        return result

    topics = DISTILLATION_BATCH_TOPICS[: max_topics or len(DISTILLATION_BATCH_TOPICS)]
    if len(topics) < needed:
        topics = topics * ((needed // len(topics)) + 1)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Destilação em massa: {needed} tópicos (atual {before}/{target_pairs})",
            level="distillation-batch",
        )

    distilled: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for topic in topics:
        if _count_distillation_pairs() >= target_pairs:
            break
        try:
            row = distillation.distill_topic(
                topic,
                context="Ecossistema Ravenna — fábrica de software de excelência sob demanda.",
                tags=["batch-distillation", "software-excellence", "brain-corpus"],
                sync_cloud=False,
            )
            distilled.append(
                {
                    "topic": topic,
                    "pair_id": row.get("pair_id"),
                    "similarity": row.get("similarity_score"),
                }
            )
            if broadcast_observer:
                agent_collaboration._broadcast_to_observer(
                    "data-engineer",
                    f"Destilado: {topic[:60]}… (pair #{row.get('pair_id')})",
                    level="distillation-batch",
                )
        except Exception as exc:
            errors.append({"topic": topic, "error": str(exc)[:200]})
            if len(errors) >= 3 and not distilled:
                break

    after = _count_distillation_pairs()
    knowledge.add_note(
        "[Fábrica] Destilação em massa",
        (
            f"Pares: {before} → {after} (meta {target_pairs})\n\n"
            f"Destilados: {len(distilled)}\n"
            f"Erros: {len(errors)}\n\n"
            f"```json\n{json.dumps(distilled[:12], ensure_ascii=False, indent=2)}\n```"
        ),
        tags=["distillation-batch", "software-excellence", "brain-corpus"],
    )

    brain_result = None
    if refresh_brain and after > before:
        brain_result = run_brain_pipeline(dry_run=False, broadcast_observer=broadcast_observer)

    excellence = assess_excellence()
    return {
        "success": after >= target_pairs or len(distilled) > 0,
        "action": "distillation_batch",
        "pairs_before": before,
        "pairs_after": after,
        "target_pairs": target_pairs,
        "distilled": len(distilled),
        "topics_attempted": min(len(topics), needed + len(errors)),
        "results": distilled,
        "errors": errors,
        "brain": brain_result,
        "excellence": excellence["summary"],
        "missing_must": excellence.get("missing_must", []),
    }


def run_brain_pipeline(*, dry_run: bool = False, broadcast_observer: bool = True) -> dict[str, Any]:
    """Exporta treino, gera Modelfile e cria o modelo raven no Ollama."""
    from learning_agent.core import agent_collaboration, agent_learning_loop, knowledge

    export_result = agent_learning_loop.run_export_training(broadcast_observer=broadcast_observer)
    model_result = finetune.create_ollama_model(dry_run=dry_run)

    knowledge.add_note(
        "[Cérebro Ravenna] Pipeline de treino",
        (
            f"## Export\n{json.dumps(export_result.get('base_export', {}), ensure_ascii=False)[:1200]}\n\n"
            f"## Modelo\n{json.dumps({k: model_result.get(k) for k in ('target_model', 'success', 'dry_run', 'create_command')}, ensure_ascii=False)}"
        ),
        tags=["brain-pipeline", "raven", "training-export"],
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Cérebro local: {model_result.get('target_model', STUDENT_FINETUNE_MODEL)} "
            f"({'dry-run' if dry_run else 'criação'})",
            level="brain-pipeline",
        )

    return {
        "success": True,
        "action": "brain_pipeline",
        "export": export_result,
        "model": model_result,
        "hint": (
            f"Configure CHAT_MODEL={STUDENT_FINETUNE_MODEL} no .env após ollama create"
            if dry_run
            else "Reinicie a API com CHAT_MODEL apontando para o modelo local"
        ),
    }


def run_software_excellence_sprint(*, broadcast_observer: bool = True) -> dict[str, Any]:
    """Sprint no próximo gap da fábrica de software."""
    from learning_agent.core import agent_autonomy, agent_collaboration, knowledge

    report = assess_excellence()
    nxt = report.get("next_objective")
    if not nxt:
        return {
            "success": True,
            "action": "software_excellence_sprint",
            "complete": True,
            "message": "Ecossistema pronto para criar software de excelência sob demanda",
        }

    action = nxt.get("action", "capability_assessment")
    owner = nxt.get("owner", "ravenna")
    title = nxt.get("title", nxt["id"])

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            owner,
            f"Objetivo fábrica: «{title}» — ação «{action}»",
            level="software-excellence",
        )

    if action == "brain_pipeline":
        result = run_brain_pipeline(dry_run=False, broadcast_observer=broadcast_observer)
    else:
        result = agent_autonomy.execute_autonomy_action(action)

    knowledge.add_note(
        f"[Fábrica] {title}",
        (
            f"## Gap\n{nxt.get('description', '')}\n\n"
            f"## ID\n{nxt['id']}\n\n"
            f"## Progresso\n"
            f"Fábrica: {report['summary']['factory_ready_pct']}%\n"
            f"Prática IDE: {report['summary']['practice_pct']}%\n\n"
            f"## Resultado\n{json.dumps(result, ensure_ascii=False)[:2000]}"
        ),
        tags=["software-excellence", f"objective:{nxt['id']}", f"agent:{owner}"],
    )

    fresh = assess_excellence()
    return {
        "success": True,
        "action": "software_excellence_sprint",
        "complete": fresh["complete"],
        "objective": nxt,
        "executed_action": action,
        "owner": owner,
        "result": result,
        "completion": fresh["summary"],
    }


def _persist_snapshot(report: dict[str, Any]) -> None:
    slim = {
        "complete": report["complete"],
        "north_star": report["north_star"],
        "summary": report["summary"],
        "missing_must": report["missing_must"][:12],
        "next_objective_id": (report.get("next_objective") or {}).get("id"),
        "brain": report.get("brain", {}),
    }
    SOFTWARE_EXCELLENCE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SOFTWARE_EXCELLENCE_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)


def load_excellence_snapshot() -> dict[str, Any]:
    if not SOFTWARE_EXCELLENCE_STATE_PATH.is_file():
        return {"complete": False, "summary": {}}
    try:
        with SOFTWARE_EXCELLENCE_STATE_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"complete": False, "summary": {}}
