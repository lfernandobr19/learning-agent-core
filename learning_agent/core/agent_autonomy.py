"""Autonomia dos agentes — iniciativa própria, perguntas entre peers, pesquisa e dev colaborativo."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import json

from learning_agent import db
from learning_agent.config import (
    AUTO_AGENT_AUTONOMY,
    AUTONOMY_INTERVAL_SECONDS,
    AUTONOMY_PREFS_PATH,
    PROJECT_ROOT,
    TEACHER_API_BASE,
    TEACHER_API_KEY,
    TEACHER_MODEL,
)
from learning_agent.core import agent_collaboration, agent_learning_loop, knowledge, llm as llm_core
from learning_agent.identity import AGENT_NAME, RAVENNA_SYSTEM_BRIEF

SPRINTS_DIR = PROJECT_ROOT / "agents" / "collab-sprints"

AUTONOMY_ACTIONS = [
    "peer_question",
    "peer_quiz",
    "research_gaps",
    "weak_area_drill",
    "consult_ravenna",
    "consult_teacher",
    "distill_for_peers",
    "code_walk",
    "collab_dev_sprint",
    "execute_micro_sprint",
    "proof_gate",
    "error_roundtable",
    "peer_review",
    "roundtable",
    "graph_sync",
    "evolve_playbook",
    "gap_to_skill",
    "active_learning",
    "repo_study",
    "scheduled_consolidation",
    "ravenna_hands_on",
    "export_training",
    "debug_sweep",
    "agent_health_audit",
    "optimize_cycle",
    "capability_assessment",
    "mentor_session",
    "spaced_review",
    "ide_improvement_sprint",
    "ide_completion_sprint",
    "software_excellence_sprint",
    "brain_pipeline",
    "distillation_batch",
    "raven_preparation_sprint",
    "model_parity_assessment",
    "agent_study_session",
    "real_code_sprint",
    "curriculum_milestone",
    "learning_closure",
]

PEER_PAIRS = [
    ("backend-lead", "frontend-lead"),
    ("frontend-lead", "qa-guardian"),
    ("qa-guardian", "backend-lead"),
    ("data-engineer", "backend-lead"),
    ("backend-lead", "data-engineer"),
    ("reliability-lead", "qa-guardian"),
    ("reliability-lead", "backend-lead"),
]

DEV_SPRINT_TOPICS = [
    "endpoint de health + teste de integração mínimo",
    "componente React de status dos agentes + teste Vitest",
    "script de validação QA para o ecossistema multi-agente",
    "pipeline de indexação de notas peer-learning no RAG",
]

_autonomy_state: dict[str, Any] = {
    "running": False,
    "interval_seconds": 300,
    "cycle": 0,
    "current_action": "",
    "current_topic": "",
    "last_run_at": "",
    "last_result_summary": "",
    "task_id": "",
}
_autonomy_task: asyncio.Task[None] | None = None


def load_autonomy_prefs() -> dict[str, Any]:
    if not AUTONOMY_PREFS_PATH.is_file():
        return {"always_on": False, "interval_seconds": AUTONOMY_INTERVAL_SECONDS}
    try:
        with AUTONOMY_PREFS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {"always_on": False}
    except (json.JSONDecodeError, OSError):
        return {"always_on": False, "interval_seconds": AUTONOMY_INTERVAL_SECONDS}


def save_autonomy_prefs(*, always_on: bool, interval_seconds: int) -> dict[str, Any]:
    AUTONOMY_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "always_on": always_on,
        "interval_seconds": max(90, interval_seconds),
        "updated_at": _utcnow(),
    }
    with AUTONOMY_PREFS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


async def set_always_on(
    enabled: bool,
    *,
    interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Persiste preferência e inicia/para autonomia."""
    prefs = load_autonomy_prefs()
    interval = interval_seconds or prefs.get("interval_seconds") or AUTONOMY_INTERVAL_SECONDS
    saved = save_autonomy_prefs(always_on=enabled, interval_seconds=interval)

    if enabled:
        result = await start_autonomy(interval)
        result["always_on"] = True
        result["prefs"] = saved
        return result

    result = await stop_autonomy()
    result["always_on"] = False
    result["prefs"] = saved
    return result


async def maybe_auto_start() -> dict[str, Any] | None:
    """Inicia autonomia ao subir a API se env ou preferência salva."""
    prefs = load_autonomy_prefs()
    if not (AUTO_AGENT_AUTONOMY or prefs.get("always_on")):
        return None
    if _autonomy_state.get("running"):
        return get_autonomy_status()
    interval = int(prefs.get("interval_seconds") or AUTONOMY_INTERVAL_SECONDS)
    return await start_autonomy(interval)


def _utcnow() -> str:
    return db._utcnow()


def _manifest(agent: str) -> dict[str, Any]:
    from learning_agent.core.agent_collaboration import _load_manifest

    return _load_manifest(agent) or {}


def _llm_chat(system: str, user: str, *, max_tokens: int = 320) -> tuple[str, str]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return llm_core.chat_with_fallback(messages, max_tokens=max_tokens, temperature=0.55)
    except Exception:
        return "(sem resposta do modelo — verifique Ollama ou TEACHER_API_KEY)", "fallback"


def _total_gaps() -> int:
    total = 0
    for agent in agent_collaboration.list_collaborative_agents():
        name = agent.get("name")
        if not name:
            continue
        report = agent_collaboration.detect_knowledge_gaps(name)
        total += report.get("gap_count", 0)
    return total


def _recent_error_count() -> int:
    db.init_db()
    with db.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM learning_errors").fetchone()
    return int(row["c"]) if row else 0


def pick_autonomy_action(cycle: int) -> str:
    """Escolhe a próxima ação com base em lacunas, erros, consolidação e rotação."""
    from learning_agent.config import AGENT_STUDY_STRUCTURED

    if AGENT_STUDY_STRUCTURED:
        if cycle % 4 == 0:
            return "collab_dev_sprint"
        if cycle % 6 == 0:
            return "model_parity_assessment"
        return "agent_study_session"

    if agent_learning_loop.should_run_consolidation(cycle):
        return "scheduled_consolidation"

    from learning_agent.core import agent_capability, agent_event_triggers

    event_action = agent_event_triggers.pick_event_action()
    if event_action:
        return event_action

    from learning_agent.core import software_excellence

    if cycle % 6 == 0:
        excellence = software_excellence.assess_excellence()
        if not excellence.get("complete"):
            nxt = excellence.get("next_objective") or {}
            action = nxt.get("action")
            if action in {"brain_pipeline", "export_training"}:
                return "brain_pipeline" if action == "brain_pipeline" else "export_training"
            return "software_excellence_sprint"

    level_up = agent_capability.pick_level_up_action(cycle)
    if level_up:
        return level_up
    if cycle % 8 == 0:
        return "capability_assessment"

    gaps = _total_gaps()
    errors = _recent_error_count()

    if errors >= 1:
        return "debug_sweep" if cycle % 2 == 0 else "error_roundtable"
    if gaps >= 8:
        return "research_gaps"
    if cycle % 7 == 0:
        return "agent_health_audit"
    if cycle % 9 == 0:
        return "optimize_cycle"
    if errors >= 2 and cycle % 3 == 0:
        return "proof_gate"

    rotation = [
        "curriculum_milestone",
        "ravenna_hands_on",
        "debug_sweep",
        "mentor_session",
        "spaced_review",
        "peer_question",
        "peer_quiz",
        "weak_area_drill",
        "ide_improvement_sprint",
        "ide_completion_sprint",
        "software_excellence_sprint",
        "brain_pipeline",
        "distillation_batch",
        "raven_preparation_sprint",
        "model_parity_assessment",
        "consult_ravenna",
        "code_walk",
        "research_gaps",
        "distill_for_peers",
        "collab_dev_sprint",
        "real_code_sprint",
        "execute_micro_sprint",
        "consult_teacher",
        "peer_review",
        "roundtable",
        "graph_sync",
        "evolve_playbook",
        "active_learning",
        "repo_study",
        "gap_to_skill",
        "export_training",
        "agent_health_audit",
        "optimize_cycle",
        "proof_gate",
    ]
    return rotation[cycle % len(rotation)]


def run_peer_question_session(
    asker: str | None = None,
    answerer: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Um agente pergunta ao outro o que ele sabe — aprendizado cruzado ativo."""
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    if len(agents) < 2:
        return {"success": False, "error": "precisa de pelo menos 2 agentes"}

    pair = PEER_PAIRS[len(agents) % len(PEER_PAIRS)]
    ask = asker or pair[0]
    ans = answerer or pair[1]
    if ask not in agents:
        ask = agents[0]
    if ans not in agents or ans == ask:
        ans = next((a for a in agents if a != ask), agents[0])

    ask_m = _manifest(ask)
    ans_m = _manifest(ans)
    thread_id = f"peer-q-{uuid.uuid4().hex[:10]}"

    question, _ = _llm_chat(
        f"Você é {ask_m.get('display_name', ask)}. Gere UMA pergunta técnica em português "
        f"para descobrir o que {ans_m.get('display_name', ans)} sabe sobre integração do projeto. "
        "Seja específico. Só a pergunta, sem prefácio.",
        f"Seu foco: {ask_m.get('focus', '')}. Domínio do outro: {ans_m.get('focus', '')}.",
        max_tokens=120,
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            ask, f"Pergunto a {ans}: {question}", level="peer-question"
        )

    answer, _ = _llm_chat(
        f"Você é {ans_m.get('display_name', ans)}, arquétipo {ans_m.get('archetype', '')}. "
        f"Responda em português, 3-5 frases, compartilhe o que sabe de verdade.",
        f"Pergunta de {ask}: {question}",
        max_tokens=280,
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            ans, f"Respondo a {ask}: {answer}", level="peer-answer"
        )

    follow_up, _ = _llm_chat(
        f"Você é {ask_m.get('display_name', ask)}. Com base na resposta, diga em 1-2 frases "
        "o que aprendeu ou qual pergunta de follow-up faria.",
        f"Sua pergunta: {question}\nResposta de {ans}: {answer}",
        max_tokens=100,
    )

    agent_collaboration.share_insight(ask, f"Perguntei: {question}", "peer-question", to_agents=[ans])
    agent_collaboration.share_insight(ans, answer, "peer-answer", to_agents=[ask])
    agent_collaboration.share_insight(
        ask, f"Aprendizado: {follow_up}", "peer-followup", to_agents=["all"]
    )

    db.init_db()
    with db.get_connection() as conn:
        for role, msg, typ in [
            (ask, question, "peer_question"),
            (ans, answer, "peer_answer"),
            (ask, follow_up, "peer_followup"),
        ]:
            conn.execute(
                """
                INSERT INTO agent_exchanges
                    (thread_id, from_agent, to_agent, message, exchange_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, role, ans if role == ask else ask, msg, typ, _utcnow()),
            )

    return {
        "success": True,
        "action": "peer_question",
        "thread_id": thread_id,
        "asker": ask,
        "answerer": ans,
        "question": question,
        "answer": answer,
        "follow_up": follow_up,
    }


def agent_consult_ravenna(
    from_agent: str,
    question: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agente consulta a Ravenna ativamente."""
    slug = from_agent.strip().lower().replace("_", "-")
    m = _manifest(slug)
    if not question:
        gaps = agent_collaboration.detect_knowledge_gaps(slug)
        top = gaps.get("gaps", [{}])[0].get("topic", m.get("focus", "o projeto"))
        question = f"Ravenna, como devo abordar «{top}» no meu domínio ({m.get('archetype', '')})?"

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug, f"Consulto a Ravenna: {question}", level="consult-ravenna"
        )

    reply, model = _llm_chat(
        f"{RAVENNA_SYSTEM_BRIEF} O agente {m.get('display_name', slug)} "
        f"({slug}) consulta você. Responda em português, 4-6 frases, clara, acolhedora e técnica.",
        question,
        max_tokens=350,
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna", f"Para {slug}: {reply}", level="ravenna-reply"
        )

    agent_collaboration.share_insight(slug, f"Ravenna respondeu: {reply}", "consult-ravenna", to_agents=["all"])
    knowledge.add_note(
        f"[Consulta] {slug} → Ravenna",
        f"Pergunta: {question}\n\nResposta Ravenna:\n{reply}",
        tags=["consult-ravenna", f"agent:{slug}", "autonomy"],
    )

    return {
        "success": True,
        "action": "consult_ravenna",
        "from_agent": slug,
        "question": question,
        "reply": reply,
        "model": model,
    }


def agent_consult_teacher(
    from_agent: str,
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agente consulta o professor (teacher API / distillation)."""
    slug = from_agent.strip().lower().replace("_", "-")
    m = _manifest(slug)
    subject = topic.strip() or m.get("focus", "melhores práticas do domínio")

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug, f"Consulto o professor sobre: {subject}", level="consult-teacher"
        )

    reply = ""
    model = "teacher"
    source = "distillation"

    try:
        from learning_agent.core import distillation

        if distillation.is_configured():
            result = distillation.distill_topic(
                subject,
                context=f"Pergunta do agente {slug} ({m.get('archetype', '')})",
                tags=["consult-teacher", f"agent:{slug}", "autonomy"],
            )
            reply = str(result.get("teacher_output") or result.get("summary") or result)[:2000]
        else:
            raise ValueError("distillation não configurada")
    except Exception:
        source = "teacher-chat"
        if TEACHER_API_KEY:
            reply = llm_core.chat_complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Você é um professor sênior de engenharia de software. "
                            "Responda em português, didático e técnico, 5-8 frases."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"[Agente {slug}] Tópico: {subject}",
                    },
                ],
                base_url=TEACHER_API_BASE,
                api_key=TEACHER_API_KEY,
                model=TEACHER_MODEL,
                max_tokens=400,
            )
            model = TEACHER_MODEL
        else:
            reply, model = _llm_chat(
                "Professor substituto — responda como mentor técnico sênior.",
                f"Tópico para o agente {slug}: {subject}",
            )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Professor responde a {slug} ({subject}): {reply[:400]}…",
            level="teacher-reply",
        )

    agent_collaboration.share_insight(
        slug, f"Professor ensinou: {reply[:500]}", subject, to_agents=["all"]
    )

    return {
        "success": True,
        "action": "consult_teacher",
        "from_agent": slug,
        "topic": subject,
        "reply": reply,
        "source": source,
        "model": model,
    }


def run_collab_dev_sprint(
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agentes propõem e planejam software juntos — testes e melhorias incluídos."""
    agents = agent_collaboration.list_collaborative_agents()
    names = [a["name"] for a in agents if a.get("name")]
    if not names:
        return {"success": False, "error": "nenhum agente disponível"}

    sprint_topic = topic.strip() or DEV_SPRINT_TOPICS[len(names) % len(DEV_SPRINT_TOPICS)]
    thread_id = f"sprint-{uuid.uuid4().hex[:10]}"
    contributions: list[dict[str, str]] = []

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Sprint colaborativo iniciado: {sprint_topic}",
            level="collab-dev-start",
        )

    for name in names:
        m = _manifest(name)
        contrib, _ = _llm_chat(
            f"Você é {m.get('display_name', name)} ({m.get('archetype', '')}). "
            "Proponha em 3-4 frases sua parte no mini-projeto: o que implementaria, "
            "como testaria e qual melhor prática aplicaria.",
            f"Sprint colaborativo: {sprint_topic}",
            max_tokens=220,
        )
        contributions.append({"agent": name, "contribution": contrib})
        if broadcast_observer:
            agent_collaboration._broadcast_to_observer(name, contrib, level="collab-dev")
        agent_collaboration.share_insight(name, contrib, sprint_topic, to_agents=names)

    bullets = "\n".join(f"### {c['agent']}\n{c['contribution']}" for c in contributions)
    plan, _ = _llm_chat(
        f"{RAVENNA_SYSTEM_BRIEF} Unifique as propostas em um plano de sprint executável, tom claro e acolhedor.",
        f"Tópico: {sprint_topic}\n\nPropostas:\n{bullets}\n\n"
        "Inclua: objetivo, tarefas por agente, testes, critérios de aceite, melhorias.",
        max_tokens=500,
    )

    qa_plan = ""
    if "qa-guardian" in names:
        qa_plan, _ = _llm_chat(
            "Você é QA Guardian. Liste checklist de vistoria e testes para este sprint.",
            f"Plano:\n{plan}",
            max_tokens=280,
        )

    SPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    sprint_file = SPRINTS_DIR / f"{thread_id}.md"
    sprint_body = (
        f"# Sprint colaborativo — {sprint_topic}\n\n"
        f"**ID:** {thread_id}\n**Data:** {_utcnow()}\n\n"
        f"## Plano unificado (Ravenna)\n\n{plan}\n\n"
        f"## Contribuições\n\n{bullets}\n\n"
        f"## Vistoria QA\n\n{qa_plan or '—'}\n"
    )
    sprint_file.write_text(sprint_body, encoding="utf-8")

    knowledge.add_note(
        f"[Sprint] {sprint_topic[:60]}",
        sprint_body,
        tags=["collab-dev", "autonomy", "agent-sprint"],
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            "ravenna",
            f"Plano do sprint: {plan[:500]}",
            level="collab-dev-plan",
        )

    return {
        "success": True,
        "action": "collab_dev_sprint",
        "thread_id": thread_id,
        "topic": sprint_topic,
        "contributions": contributions,
        "plan": plan,
        "qa_checklist": qa_plan,
        "sprint_file": str(sprint_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def execute_autonomy_action(action: str, *, topic: str = "") -> dict[str, Any]:
    """Executa uma ação autônoma."""
    agents = agent_collaboration.list_collaborative_agents()
    names = [a["name"] for a in agents if a.get("name")]
    idx = lambda i: names[i % len(names)] if names else ""

    dispatch: dict[str, Any] = {
        "peer_question": lambda: run_peer_question_session(),
        "peer_quiz": lambda: agent_learning_loop.run_peer_quiz(),
        "research_gaps": lambda: {
            "success": True,
            "action": action,
            "research": [
                agent_collaboration.agent_research_gaps(n, max_topics=1) for n in names[:4]
            ],
        },
        "weak_area_drill": lambda: agent_learning_loop.run_weak_area_drill(idx(0)),
        "consult_ravenna": lambda: agent_consult_ravenna(idx(0)) if names else {"success": False, "error": "sem agentes"},
        "consult_teacher": lambda: agent_consult_teacher(idx(1), topic=topic) if names else {"success": False, "error": "sem agentes"},
        "distill_for_peers": lambda: agent_learning_loop.run_distill_for_peers(topic=topic),
        "code_walk": lambda: agent_learning_loop.run_code_walk(idx(cycle_hint())),
        "collab_dev_sprint": lambda: run_collab_dev_sprint(topic=topic),
        "execute_micro_sprint": lambda: agent_learning_loop.run_execute_micro_sprint(topic=topic),
        "proof_gate": lambda: agent_learning_loop.run_proof_gate(),
        "error_roundtable": lambda: agent_learning_loop.run_error_roundtable(),
        "peer_review": lambda: agent_learning_loop.run_peer_review(),
        "roundtable": lambda: agent_collaboration.run_agent_roundtable(
            topic or "práticas e lacunas — troca ativa entre especialistas",
            broadcast_observer=True,
        ),
        "graph_sync": lambda: agent_learning_loop.run_graph_sync(topic=topic),
        "evolve_playbook": lambda: agent_learning_loop.run_evolve_playbook(idx(0)),
        "gap_to_skill": lambda: agent_learning_loop.run_gap_to_skill(),
        "active_learning": lambda: agent_learning_loop.run_active_learning_agents(),
        "repo_study": lambda: agent_learning_loop.run_repo_study(idx(2)),
        "scheduled_consolidation": lambda: agent_learning_loop.run_scheduled_consolidation(),
        "ravenna_hands_on": lambda: agent_learning_loop.run_ravenna_hands_on(topic=topic),
        "export_training": lambda: agent_learning_loop.run_export_training(),
        "debug_sweep": lambda: agent_learning_loop.run_debug_sweep(),
        "agent_health_audit": lambda: agent_learning_loop.run_agent_health_audit(),
        "optimize_cycle": lambda: agent_learning_loop.run_optimize_cycle(),
        "capability_assessment": lambda: agent_learning_loop.run_capability_assessment(),
        "mentor_session": lambda: __import__(
            "learning_agent.core.agent_mentoring", fromlist=["run_mentor_session"]
        ).run_mentor_session(),
        "spaced_review": lambda: __import__(
            "learning_agent.core.agent_spaced_review", fromlist=["run_spaced_review"]
        ).run_spaced_review(idx(0)),
        "ide_improvement_sprint": lambda: __import__(
            "learning_agent.core.agent_ide_practice", fromlist=["run_ide_improvement_sprint"]
        ).run_ide_improvement_sprint(idx(1)),
        "ide_completion_sprint": lambda: __import__(
            "learning_agent.core.ide_objectives", fromlist=["run_ide_completion_sprint"]
        ).run_ide_completion_sprint(),
        "software_excellence_sprint": lambda: __import__(
            "learning_agent.core.software_excellence", fromlist=["run_software_excellence_sprint"]
        ).run_software_excellence_sprint(),
        "brain_pipeline": lambda: __import__(
            "learning_agent.core.software_excellence", fromlist=["run_brain_pipeline"]
        ).run_brain_pipeline(dry_run=False),
        "distillation_batch": lambda: __import__(
            "learning_agent.core.software_excellence", fromlist=["run_distillation_batch"]
        ).run_distillation_batch(),
        "raven_preparation_sprint": lambda: __import__(
            "learning_agent.core.raven_readiness", fromlist=["run_preparation_sprint"]
        ).run_preparation_sprint(),
        "model_parity_assessment": lambda: __import__(
            "learning_agent.core.agent_model_parity", fromlist=["run_model_parity_assessment"]
        ).run_model_parity_assessment(idx(0)),
        "agent_study_session": lambda: __import__(
            "learning_agent.core.agent_study_methodology", fromlist=["run_ecosystem_study_round"]
        ).run_ecosystem_study_round(broadcast_observer=True, light=False, full_verify=False),
        "real_code_sprint": lambda: agent_learning_loop.run_real_code_sprint(idx(0), topic=topic),
        "curriculum_milestone": lambda: agent_learning_loop.run_curriculum_milestone(idx(0)),
        "learning_closure": lambda: agent_learning_loop.run_learning_closure(
            "manual", topic or "revisão", {}, agent=idx(0)
        ),
    }

    handler = dispatch.get(action)
    if handler:
        return handler()
    return {"success": False, "error": f"ação desconhecida: {action}"}


def cycle_hint() -> int:
    return int(_autonomy_state.get("cycle", 0))


def run_autonomy_cycle(cycle: int, *, fixed_topic: str = "") -> dict[str, Any]:
    action = pick_autonomy_action(cycle)
    _autonomy_state["current_action"] = action
    topic = fixed_topic
    if action == "roundtable" and not topic:
        topic = agent_collaboration.COLLAB_ROTATION_TOPICS[
            cycle % len(agent_collaboration.COLLAB_ROTATION_TOPICS)
        ]
    _autonomy_state["current_topic"] = topic or action

    agent_collaboration._broadcast_to_observer(
        "ravenna",
        f"Autonomia ({cycle}): iniciando «{action}»"
        + (f" — {topic}" if topic and action != "peer_question" else ""),
        level="autonomy-start",
    )

    result = execute_autonomy_action(action, topic=topic)

    if result.get("success") is not False and action != "learning_closure":
        agents = agent_collaboration.list_collaborative_agents()
        agent_name = ""
        if agents:
            agent_name = agents[cycle % len(agents)].get("name", "")
        closure = agent_learning_loop.run_learning_closure(
            action,
            topic or str(result.get("topic", action)),
            result,
            agent=agent_name or "ravenna",
        )
        result["learning_closure"] = closure

    summary = (
        result.get("plan")
        or result.get("question")
        or result.get("topic")
        or result.get("learning_closure", {}).get("understand")
        or action
    )
    _autonomy_state["last_result_summary"] = str(summary)[:200]
    _autonomy_state["last_run_at"] = _utcnow()
    return result


async def _autonomy_loop(interval_seconds: int, fixed_topic: str = "") -> None:
    cycle = 0
    while _autonomy_state.get("running"):
        cycle += 1
        _autonomy_state["cycle"] = cycle
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            agent_collaboration._executor,
            lambda c=cycle, t=fixed_topic: run_autonomy_cycle(c, fixed_topic=t),
        )
        for _ in range(interval_seconds):
            if not _autonomy_state.get("running"):
                break
            await asyncio.sleep(1)


async def start_autonomy(interval_seconds: int = 300, topic: str = "") -> dict[str, Any]:
    global _autonomy_task

    if _autonomy_state.get("running") and _autonomy_task and not _autonomy_task.done():
        return {
            "success": False,
            "error": "autonomia já em execução",
            "status": get_autonomy_status(),
        }

    if not agent_collaboration.list_collaborative_agents():
        return {"success": False, "error": "nenhum agente — scaffold_core_agents primeiro"}

    agent_collaboration._active_state["running"] = False

    _autonomy_state.update(
        {
            "running": True,
            "interval_seconds": max(90, interval_seconds),
            "cycle": 0,
            "current_action": "starting",
            "current_topic": topic or "autonomia ativa",
            "task_id": uuid.uuid4().hex[:12],
        }
    )
    _autonomy_task = asyncio.create_task(_autonomy_loop(_autonomy_state["interval_seconds"], topic))

    return {
        "success": True,
        "started": True,
        "mode": "autonomy",
        "status": get_autonomy_status(),
        "hint": (
            "Loop aberto: entender → testar → elevar. "
            f"{len(AUTONOMY_ACTIONS)} ações incluindo Ravenna mão na massa."
        ),
    }


async def stop_autonomy() -> dict[str, Any]:
    global _autonomy_task

    _autonomy_state["running"] = False
    if _autonomy_task and not _autonomy_task.done():
        _autonomy_task.cancel()
        try:
            await _autonomy_task
        except asyncio.CancelledError:
            pass
    _autonomy_task = None

    agent_collaboration._broadcast_to_observer(
        "ravenna", "Autonomia dos agentes pausada.", level="autonomy-stop"
    )

    return {"success": True, "stopped": True, "status": get_autonomy_status()}


def get_autonomy_status() -> dict[str, Any]:
    prefs = load_autonomy_prefs()
    return {
        "success": True,
        "running": bool(_autonomy_state.get("running")),
        "mode": "autonomy" if _autonomy_state.get("running") else "idle",
        "always_on": bool(prefs.get("always_on")) or AUTO_AGENT_AUTONOMY,
        "always_on_persisted": bool(prefs.get("always_on")),
        "auto_from_env": AUTO_AGENT_AUTONOMY,
        "interval_seconds": _autonomy_state.get("interval_seconds", 300),
        "cycle": _autonomy_state.get("cycle", 0),
        "current_action": _autonomy_state.get("current_action", ""),
        "current_topic": _autonomy_state.get("current_topic", ""),
        "last_run_at": _autonomy_state.get("last_run_at", ""),
        "last_result_summary": _autonomy_state.get("last_result_summary", ""),
        "actions": AUTONOMY_ACTIONS,
        "agents": [a["name"] for a in agent_collaboration.list_collaborative_agents()],
    }
