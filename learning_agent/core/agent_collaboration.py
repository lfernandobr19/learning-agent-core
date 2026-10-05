"""Colaboração entre agentes — diálogo, troca de insights, pesquisa e consolidação."""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from learning_agent import db
from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_factory, knowledge, quiz, web
from learning_agent.core import llm as llm_core
from learning_agent.identity import AGENT_NAME, RAVENNA_SYSTEM_BRIEF

PROJECTS_DIR = PROJECT_ROOT / "agents" / "projects"
ARCHETYPES_DIR = PROJECT_ROOT / "agents" / "archetypes"

COLLAB_ROTATION_TOPICS = [
    "integração backend e frontend na Ravenna IDE",
    "checklist de qualidade e regressões",
    "pipelines de dados, SQL e RAG",
    "lacunas técnicas — o que pesquisar e aplicar",
    "práticas consolidadas para o ecossistema",
]

_active_state: dict[str, Any] = {
    "running": False,
    "interval_seconds": 300,
    "cycle": 0,
    "current_topic": "",
    "last_run_at": "",
    "task_id": "",
}
_active_task: asyncio.Task[None] | None = None
_executor = ThreadPoolExecutor(max_workers=1)

ARCHETYPE_FALLBACK_VIEWS: dict[str, str] = {
    "backend": "Do lado servidor: contratos API, persistência, async e testes de integração.",
    "frontend": "Do lado UI: componentes, acessibilidade, performance e testes Vitest.",
    "qa-inspector": "Do lado qualidade: riscos, cobertura, regressões e evidências reproduzíveis.",
    "data": "Do lado dados: schema, pipelines, validação e métricas pós-transformação.",
    "custom": "Do meu domínio: padrões específicos e critérios de sucesso do escopo.",
}


def _utcnow() -> str:
    return db._utcnow()


def _load_manifest(agent_name: str) -> dict[str, Any] | None:
    path = PROJECTS_DIR / agent_name / "manifest.yaml"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else None


def _load_archetype(archetype_id: str) -> dict[str, Any]:
    path = ARCHETYPES_DIR / f"{archetype_id}.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _broadcast_to_observer(from_agent: str, message: str, *, level: str = "collab") -> None:
    """Envia mensagem ao painel Observador da IDE (WebSocket)."""
    try:
        from learning_agent.core import theater

        display = from_agent.replace("-", " ").title()
        if from_agent.lower() == AGENT_NAME.lower():
            role, label = "ravenna", AGENT_NAME
        else:
            role, label = from_agent, display

        coro = theater.post_agent_message(role, label, message, level=level)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
        else:
            _executor.submit(asyncio.run, coro).result(timeout=8)
    except Exception:
        pass


def list_collaborative_agents() -> list[dict[str, Any]]:
    listing = agent_factory.list_agents()
    agents = []
    for item in listing.get("projects", []):
        agents.append(
            {
                "name": item.get("name"),
                "display_name": item.get("display_name"),
                "archetype": item.get("archetype"),
                "focus": item.get("focus"),
                "learning_tags": _learning_tags(item.get("name", "")),
            }
        )
    return agents


def _learning_tags(agent_name: str) -> list[str]:
    manifest = _load_manifest(agent_name)
    if manifest:
        learning = manifest.get("learning")
        if isinstance(learning, dict):
            tags = learning.get("tags", [])
            if tags:
                return list(tags)
        arch = _load_archetype(str(manifest.get("archetype", "")))
        return list(arch.get("learning_tags", []))
    return [agent_name]


def _record_exchange(
    *,
    thread_id: str,
    from_agent: str,
    message: str,
    to_agent: str = "",
    exchange_type: str = "dialogue",
) -> None:
    db.init_db()
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_exchanges
                (thread_id, from_agent, to_agent, message, exchange_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (thread_id, from_agent, to_agent, message, exchange_type, _utcnow()),
        )


def _record_insight(
    *,
    from_agent: str,
    topic: str,
    content: str,
    to_agents: list[str],
    note_id: int | None,
    tags: list[str],
) -> int:
    db.init_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_insights
                (from_agent, to_agents, topic, content, note_id, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                from_agent,
                json.dumps(to_agents, ensure_ascii=False),
                topic,
                content,
                note_id,
                json.dumps(tags, ensure_ascii=False),
                _utcnow(),
            ),
        )
        return int(cursor.lastrowid)


def share_insight(
    from_agent: str,
    insight: str,
    topic: str,
    *,
    to_agents: list[str] | None = None,
) -> dict[str, Any]:
    """Agente compartilha descoberta com peers — persiste nota e troca entre agentes."""
    from_slug = from_agent.strip().lower().replace("_", "-")
    peers = to_agents or [
        a["name"]
        for a in list_collaborative_agents()
        if a.get("name") and a["name"] != from_slug
    ]
    if not peers:
        peers = ["all"]

    tags = _learning_tags(from_slug) + [
        "peer-learning",
        f"agent:{from_slug}",
        "agent-exchange",
    ]
    for peer in peers:
        if peer != "all":
            tags.append(f"peer:{peer}")

    title = f"[Peer] {from_slug} → {topic}"
    body = (
        f"**Agente:** {from_slug}\n**Tópico:** {topic}\n**Peers:** {', '.join(peers)}\n\n"
        f"{insight.strip()}\n\n"
        f"_Compartilhado para aprendizado cruzado entre agentes._"
    )
    note = knowledge.add_note(title, body, tags=tags)
    note_id = int(note.get("note_id") or note.get("id") or 0)

    thread_id = f"insight-{uuid.uuid4().hex[:12]}"
    _record_exchange(
        thread_id=thread_id,
        from_agent=from_slug,
        message=insight.strip(),
        exchange_type="insight",
    )
    insight_id = _record_insight(
        from_agent=from_slug,
        topic=topic,
        content=insight.strip(),
        to_agents=peers,
        note_id=note_id or None,
        tags=tags,
    )

    return {
        "success": True,
        "from_agent": from_slug,
        "to_agents": peers,
        "topic": topic,
        "insight_id": insight_id,
        "note_id": note_id,
        "thread_id": thread_id,
    }


def get_peer_insights(agent_name: str, limit: int = 10) -> dict[str, Any]:
    """O que outros agentes compartilharam — para este agente absorver."""
    slug = agent_name.strip().lower().replace("_", "-")
    db.init_db()

    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT from_agent, to_agents, topic, content, tags, note_id, created_at
            FROM agent_insights
            WHERE from_agent != ?
            ORDER BY id DESC LIMIT ?
            """,
            (slug, limit * 3),
        ).fetchall()

    insights: list[dict[str, Any]] = []
    for row in rows:
        try:
            tags = json.loads(row["tags"] or "[]")
        except json.JSONDecodeError:
            tags = []
        try:
            to_agents = json.loads(row["to_agents"] or "[]")
        except json.JSONDecodeError:
            to_agents = []

        if "all" in to_agents or slug in to_agents or f"peer:{slug}" in tags:
            insights.append(
                {
                    "from_agent": row["from_agent"],
                    "topic": row["topic"],
                    "content": row["content"],
                    "note_id": row["note_id"],
                    "created_at": row["created_at"],
                }
            )
        if len(insights) >= limit:
            break

    rag_hits = knowledge.search(f"peer-learning agent-exchange {slug}", limit=limit)
    return {
        "success": True,
        "agent": slug,
        "insights": insights,
        "knowledge_hits": rag_hits,
        "count": len(insights),
        "hint": "Use search_knowledge com tags peer-learning ao iniciar sessão",
    }


def detect_knowledge_gaps(
    agent_name: str,
    *,
    extra_topics: list[str] | None = None,
    min_hits: int = 2,
) -> dict[str, Any]:
    """Lacunas que o agente ainda não domina — pouco conhecimento indexado."""
    slug = agent_name.strip().lower().replace("_", "-")
    manifest = _load_manifest(slug)
    archetype = str(manifest.get("archetype", "custom")) if manifest else "custom"
    arch = _load_archetype(archetype)

    topics: list[str] = list(extra_topics or [])
    topics.extend(arch.get("domains", [])[:6])
    if manifest:
        focus = str(manifest.get("focus", "")).strip()
        if focus:
            topics.insert(0, focus)

    seen: set[str] = set()
    unique_topics: list[str] = []
    for t in topics:
        key = t.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique_topics.append(t.strip())

    gaps: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []

    for topic in unique_topics[:12]:
        query = f"{topic} {' '.join(_learning_tags(slug))}"
        hits = knowledge.search(query, limit=5)
        agent_hits = [
            h
            for h in hits
            if slug in str(h.get("metadata", {})).lower()
            or "peer-learning" in str(h.get("content", "")).lower()
            or any(tag in str(h.get("content", "")).lower() for tag in _learning_tags(slug))
        ]
        score = len(hits)
        if score < min_hits:
            gaps.append(
                {
                    "topic": topic,
                    "reason": f"pouco conhecimento indexado ({score} hits)",
                    "priority": "high" if score == 0 else "medium",
                }
            )
        else:
            covered.append({"topic": topic, "hits": score})

    return {
        "success": True,
        "agent": slug,
        "archetype": archetype,
        "gaps": gaps,
        "covered": covered,
        "gap_count": len(gaps),
        "learning_tags": _learning_tags(slug),
    }


def agent_research_gaps(
    agent_name: str,
    *,
    max_topics: int = 3,
    extra_topics: list[str] | None = None,
) -> dict[str, Any]:
    """Pesquisa na web o que o agente ainda não domina e indexa automaticamente."""
    slug = agent_name.strip().lower().replace("_", "-")
    gap_report = detect_knowledge_gaps(slug, extra_topics=extra_topics)
    gaps = gap_report.get("gaps", [])[:max_topics]

    researched: list[dict[str, Any]] = []
    errors: list[str] = []

    for gap in gaps:
        topic = gap["topic"]
        tags = _learning_tags(slug) + ["peer-learning", f"agent:{slug}", "auto-research"]
        try:
            result = web.search_and_learn(topic, limit=2, tags=tags)
            researched.append({"topic": topic, "result": result})
            share_insight(
                slug,
                f"Pesquisei e indexei material sobre: {topic}. Próximos passos: aplicar no projeto.",
                topic,
            )
        except Exception as exc:
            errors.append(f"{topic}: {exc}")

    return {
        "success": True,
        "agent": slug,
        "gaps_detected": len(gap_report.get("gaps", [])),
        "researched": researched,
        "errors": errors,
        "gap_report": gap_report,
    }


def _agent_reply_llm(
    agent_name: str,
    topic: str,
    *,
    thread_messages: list[dict[str, str]],
    peer_context: str = "",
) -> tuple[str, str]:
    manifest = _load_manifest(agent_name) or {}
    arch = _load_archetype(str(manifest.get("archetype", "custom")))
    display = manifest.get("display_name", agent_name)
    focus = manifest.get("focus", arch.get("focus", ""))

    system = (
        f"Você é o agente {display} ({agent_name}), arquétipo {manifest.get('archetype', 'custom')}. "
        f"Foco: {focus}. Responda em português, 2-4 frases, técnico e direto. "
        f"Compartilhe uma lição prática que outros agentes possam absorver. "
        f"A Ravenna orquestra o ecossistema."
    )
    if peer_context:
        system += f"\n\nContexto dos peers:\n{peer_context[:1200]}"

    messages = [{"role": "system", "content": system}]
    messages.extend(thread_messages)
    messages.append(
        {
            "role": "user",
            "content": f"Tópico da rodada: {topic}. Sua contribuição e uma lição para os outros agentes.",
        }
    )

    try:
        reply, model = llm_core.chat_with_fallback(messages, max_tokens=280, temperature=0.5)
        return reply, model
    except Exception:
        view = ARCHETYPE_FALLBACK_VIEWS.get(
            str(manifest.get("archetype", "custom")),
            ARCHETYPE_FALLBACK_VIEWS["custom"],
        )
        fallback = (
            f"[{display}] Sobre «{topic}»: {view} "
            f"Recomendo documentar em add_learning_note e validar com provas."
        )
        return fallback, "template-fallback"


def run_agent_roundtable(
    topic: str,
    *,
    agents: list[str] | None = None,
    max_rounds: int = 1,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agentes conversam sobre um tópico, compartilham lições e aprendem uns com os outros."""
    available = list_collaborative_agents()
    names = agents or [a["name"] for a in available if a.get("name")]
    if not names:
        return {
            "success": False,
            "error": "nenhum agente de projeto encontrado — use scaffold_agent_project primeiro",
        }

    thread_id = f"roundtable-{uuid.uuid4().hex[:12]}"
    dialogue: list[dict[str, Any]] = []
    thread_messages: list[dict[str, str]] = []
    models_used: list[str] = []

    for round_num in range(1, max_rounds + 1):
        peer_context = "\n".join(
            f"- {d['from_agent']}: {d['message'][:200]}" for d in dialogue[-len(names) :]
        )
        for agent_name in names:
            reply, model = _agent_reply_llm(
                agent_name,
                f"{topic} (rodada {round_num})",
                thread_messages=thread_messages,
                peer_context=peer_context,
            )
            models_used.append(model)
            thread_messages.append({"role": "assistant", "content": f"[{agent_name}] {reply}"})

            _record_exchange(
                thread_id=thread_id,
                from_agent=agent_name,
                message=reply,
                exchange_type="dialogue",
            )
            dialogue.append({"round": round_num, "from_agent": agent_name, "message": reply})

            if broadcast_observer:
                _broadcast_to_observer(
                    agent_name,
                    f"«{topic}» — {reply}",
                    level=f"roundtable-r{round_num}",
                )

            share_insight(
                agent_name,
                reply,
                f"{topic} — rodada {round_num}",
                to_agents=[n for n in names if n != agent_name] or ["all"],
            )

    ravenna_synthesis = _ravenna_synthesize_roundtable(topic, dialogue, names)
    _record_exchange(
        thread_id=thread_id,
        from_agent=AGENT_NAME.lower(),
        message=ravenna_synthesis,
        exchange_type="consolidation",
    )

    if broadcast_observer:
        _broadcast_to_observer(
            "ravenna",
            f"Síntese roundtable «{topic}»: {ravenna_synthesis}",
            level="roundtable-synthesis",
        )

    return {
        "success": True,
        "thread_id": thread_id,
        "topic": topic,
        "agents": names,
        "rounds": max_rounds,
        "dialogue": dialogue,
        "ravenna_synthesis": ravenna_synthesis,
        "models": list(set(models_used)),
        "insights_shared": len(dialogue),
    }


def _ravenna_synthesize_roundtable(
    topic: str,
    dialogue: list[dict[str, Any]],
    agents: list[str],
) -> str:
    bullets = "\n".join(
        f"- **{d['from_agent']}**: {d['message'][:300]}" for d in dialogue
    )
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    f"{RAVENNA_SYSTEM_BRIEF} Sintetize o roundtable em português, "
                    "5-8 frases, tom caloroso, destacando práticas consolidadas e próximos passos."
                ),
            },
            {
                "role": "user",
                "content": f"Tópico: {topic}\nAgentes: {', '.join(agents)}\n\nDiálogo:\n{bullets}",
            },
        ]
        reply, _ = llm_core.chat_with_fallback(messages, max_tokens=400, temperature=0.4)
        return reply
    except Exception:
        return (
            f"A {AGENT_NAME} consolidou o roundtable sobre «{topic}». "
            f"{len(dialogue)} contribuições de {len(agents)} agentes. "
            "Práticas registradas em peer-learning para absorção cruzada."
        )


def consolidate_agent_ecosystem(
    *,
    agents: list[str] | None = None,
    research_gaps: bool = True,
    run_roundtable: bool = True,
    topic: str = "consolidação de práticas do ecossistema de agentes",
) -> dict[str, Any]:
    """Consolida todo o ecossistema: pesquisa lacunas, roundtable, nota mestra e quizzes."""
    names = agents or [a["name"] for a in list_collaborative_agents() if a.get("name")]
    if not names:
        return {
            "success": False,
            "error": "nenhum agente — scaffold_agent_project para backend, frontend, qa, data",
        }

    research_results: list[dict[str, Any]] = []
    if research_gaps:
        for name in names:
            research_results.append(agent_research_gaps(name, max_topics=2))

    roundtable_result: dict[str, Any] | None = None
    if run_roundtable:
        roundtable_result = run_agent_roundtable(topic, agents=names, max_rounds=1)

    all_notes: list[str] = []
    for name in names:
        tags = _learning_tags(name)
        hits = knowledge.search(f"{' '.join(tags)} agent:{name}", limit=8)
        for h in hits:
            all_notes.append(f"[{name}] {h.get('content', '')[:400]}")

    peer_hits = knowledge.search("peer-learning agent-exchange", limit=15)
    synthesis_body = (
        f"# Consolidação ecossistema — {AGENT_NAME}\n\n"
        f"**Agentes:** {', '.join(names)}\n\n"
        f"## Síntese roundtable\n\n"
        f"{(roundtable_result or {}).get('ravenna_synthesis', '—')}\n\n"
        f"## Práticas por agente\n\n"
        + "\n\n".join(all_notes[:20])
        + "\n\n## Trocas peer-learning\n\n"
        + "\n".join(f"- {h.get('content', '')[:250]}" for h in peer_hits[:10])
    )

    master = knowledge.add_note(
        f"[Ecossistema] Consolidação {AGENT_NAME} — práticas dos agentes",
        synthesis_body,
        tags=["ravenna", "agent-ecosystem", "consolidation", "peer-learning"],
    )

    quizzes_created: list[dict[str, Any]] = []
    for name in names[:4]:
        manifest = _load_manifest(name) or {}
        arch = str(manifest.get("archetype", name))
        try:
            q = quiz.create_quiz(topic=f"Agente {name} — {arch}", count=2)
            quizzes_created.append(q)
        except Exception:
            pass

    return {
        "success": True,
        "agents": names,
        "research": research_results,
        "roundtable": roundtable_result,
        "master_note_id": master.get("note_id") or master.get("id"),
        "quizzes_created": len(quizzes_created),
        "peer_insights_indexed": len(peer_hits),
    }


def ravenna_absorb_all_practices() -> dict[str, Any]:
    """Ravenna absorve e consolida todas as práticas possíveis do ecossistema."""
    result = consolidate_agent_ecosystem(
        research_gaps=True,
        run_roundtable=True,
        topic="absorção total de práticas — backend, frontend, QA, dados e peers",
    )
    if not result.get("success"):
        return result

    absorb_note = knowledge.add_note(
        f"[{AGENT_NAME}] Absorção consolidada — todas as práticas",
        (
            "A Ravenna absorveu o ecossistema de agentes:\n"
            "- Pesquisa automática de lacunas por agente\n"
            "- Roundtable com troca de insights\n"
            "- Nota mestra de consolidação\n"
            "- Quizzes por domínio\n\n"
            f"Referência: nota mestra #{result.get('master_note_id')}"
        ),
        tags=["ravenna", "absorption", "all-practices", "peer-learning"],
    )

    result["absorption_note_id"] = absorb_note.get("note_id") or absorb_note.get("id")
    result["ravenna"] = AGENT_NAME
    return result


async def start_active_collaboration(
    interval_seconds: int = 300,
    topic: str = "",
) -> dict[str, Any]:
    """Inicia autonomia ativa — perguntas, pesquisa, consultas, dev colaborativo."""
    from learning_agent.core import agent_autonomy

    result = await agent_autonomy.start_autonomy(interval_seconds, topic)
    if result.get("success"):
        _active_state["running"] = True
    return result


async def stop_active_collaboration() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    result = await agent_autonomy.stop_autonomy()
    _active_state["running"] = False
    return result


def get_active_collaboration_status() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    status = agent_autonomy.get_autonomy_status()
    status["topics_rotation"] = COLLAB_ROTATION_TOPICS
    return status


def get_exchange_history(thread_id: str | None = None, limit: int = 30) -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        if thread_id:
            rows = conn.execute(
                """
                SELECT thread_id, from_agent, to_agent, message, exchange_type, created_at
                FROM agent_exchanges WHERE thread_id = ?
                ORDER BY id ASC
                """,
                (thread_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT thread_id, from_agent, to_agent, message, exchange_type, created_at
                FROM agent_exchanges ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

    return {
        "success": True,
        "exchanges": [dict(r) for r in rows],
        "count": len(rows),
    }
