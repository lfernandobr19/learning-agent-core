import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from learning_agent import db
from learning_agent.config import MCP_HTTP_PORT
from learning_agent.identity import MCP_INSTRUCTIONS
from learning_agent.core import (
    active_learning,
    chat,
    codebase,
    context,
    curriculum,
    distillation,
    errors,
    finetune,
    graph,
    knowledge,
    progress,
    proofs,
    quiz,
    sessions,
    sources,
    web,
)
from learning_agent import sync

db.init_db()

mcp = FastMCP("learning-agent", instructions=MCP_INSTRUCTIONS, json_response=True)


def _json_result(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
def search_knowledge(query: str, limit: int = 5) -> str:
    """Search the local knowledge base semantically (docs, notes, code examples)."""
    results = knowledge.search(query, limit=limit)
    return _json_result({"query": query, "results": results})


@mcp.tool()
def fetch_and_learn(url: str, title: str = "", tags: str = "") -> str:
    """Fetch a web page URL, save to docs/web/, index in knowledge base, and add a learning note."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    try:
        result = web.fetch_and_learn(url, title=title, tags=tag_list)
        return _json_result(result)
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "url": url})


@mcp.tool()
def search_web(query: str, limit: int = 5) -> str:
    """Search the internet via DuckDuckGo. Returns titles, URLs and snippets."""
    try:
        results = web.search_web(query, limit=limit)
        return _json_result({"query": query, "results": results})
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "query": query})


@mcp.tool()
def search_and_learn(query: str, limit: int = 3, tags: str = "") -> str:
    """Search the web and automatically fetch, save, and index the top results."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    try:
        result = web.search_and_learn(query, limit=limit, tags=tag_list)
        return _json_result(result)
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "query": query})


@mcp.tool()
def add_learning_note(title: str, content: str, tags: str = "") -> str:
    """Save a learned concept with optional comma-separated tags (e.g. 'Python,async')."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = knowledge.add_note(title, content, tag_list)
    return _json_result(result)


@mcp.tool()
def send_to_ravenna(project: str, title: str, content: str, author: str = "") -> str:
    """"Envia à Ravenna": promove uma ideia consolidada ao banco de conhecimento do projeto
    no SERVIDOR (via gateway HTTP). Requer REMOTE_GATEWAY_URL_REMOVED e REMOTE_TOKEN_REMOVED no .env
    quando o Cursor roda fora da máquina Ravenna."""
    from learning_agent.core import editor

    return _json_result(
        editor.promote_project_note_via_http(
            project, title, content, author=author or ""
        )
    )


@mcp.tool()
def get_progress() -> str:
    """Return study progress: recent notes, weak areas, and due reviews."""
    return _json_result(progress.get_progress())


@mcp.tool()
def get_next_topic() -> str:
    """Return the next unstudied topic from docs/curriculo.md curriculum."""
    return _json_result(curriculum.get_next_topic())


@mcp.tool()
def get_curriculum_overview() -> str:
    """Return curriculum progress breakdown by level."""
    return _json_result(curriculum.get_curriculum_overview())


@mcp.tool()
def create_quiz(topic: str = "general", count: int = 3) -> str:
    """Generate quiz questions for a programming topic."""
    result = quiz.create_quiz(topic, count)
    return _json_result(result)


@mcp.tool()
def record_answer(quiz_item_id: int, correct: bool, response: str = "") -> str:
    """Record a quiz answer and update spaced-repetition schedule."""
    try:
        result = quiz.record_answer(quiz_item_id, correct, response)
        return _json_result(result)
    except ValueError as exc:
        return _json_result({"error": str(exc)})


@mcp.tool()
def sync_to_cloud() -> str:
    """Push local learning data snapshot to cloud (requires Supabase config)."""
    return _json_result(sync.push_to_cloud())


@mcp.tool()
def sync_from_cloud() -> str:
    """Restore local learning data from cloud snapshot."""
    return _json_result(sync.pull_from_cloud())


@mcp.tool()
def run_proofs() -> str:
    """Run full proof suite: SQLite, ChromaDB, cloud sync, Python execution."""
    return _json_result(proofs.run_full_proof_suite())


@mcp.tool()
def prove_python_code(code: str, expected_output: str = "") -> str:
    """Execute Python code and verify it runs correctly (real proof)."""
    check = proofs.prove_python_runs(code, expected_in_output=expected_output)
    return _json_result({"all_passed": check["passed"], "checks": [check]})


@mcp.tool()
def verify_learning(title: str, note_id: int = 0) -> str:
    """Verify a learning item exists in DB, disk, and RAG search."""
    result: dict[str, Any] = {"title": title}
    if note_id:
        result["note_id"] = note_id
    return _json_result(proofs.prove_learning_result(result))


@mcp.tool()
def distill_topic(topic: str, context: str = "", tags: str = "") -> str:
    """Knowledge Distillation: teacher model generates rich knowledge, student model distills it."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    try:
        result = distillation.distill_topic(topic, context=context, tags=tag_list)
        return _json_result(result)
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "topic": topic})


@mcp.tool()
def distill_from_note(note_id: int) -> str:
    """Run Knowledge Distillation on an existing learning note."""
    try:
        return _json_result(distillation.distill_from_note(note_id))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "note_id": note_id})


@mcp.tool()
def distill_from_cursor(
    topic: str,
    teacher_content: str,
    context: str = "",
    teacher_model: str = "cursor",
) -> str:
    """Destilação com Cursor como professor — você gera o conteúdo rico; o aluno local absorve."""
    try:
        return _json_result(
            distillation.distill_from_teacher_content(
                topic,
                teacher_content,
                context=context,
                teacher_model=teacher_model or "cursor",
            )
        )
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "topic": topic})


@mcp.tool()
def get_distillation_status() -> str:
    """Return Knowledge Distillation config status and pair count."""
    return _json_result(distillation.get_status())


@mcp.tool()
def index_codebase(dirs: str = "learning_agent") -> str:
    """Index project source code with intelligent chunking (functions, classes, sections)."""
    dir_list = [d.strip() for d in dirs.split(",") if d.strip()] if dirs else None
    return _json_result(codebase.index_codebase(dir_list))


@mcp.tool()
def search_code(query: str, limit: int = 5) -> str:
    """Semantic search over indexed codebase chunks."""
    return _json_result({"query": query, "results": codebase.search_code(query, limit=limit)})


@mcp.tool()
def record_session(summary: str, topics: str = "", decisions: str = "") -> str:
    """Save session memory: summary, comma-separated topics and decisions."""
    topic_list = [t.strip() for t in topics.split(",") if t.strip()] if topics else []
    decision_list = [d.strip() for d in decisions.split(",") if d.strip()] if decisions else []
    return _json_result(sessions.record_session(summary, topic_list, decision_list))


@mcp.tool()
def recall_sessions(query: str, limit: int = 5) -> str:
    """Recall past agent sessions related to a query."""
    return _json_result({"query": query, "sessions": sessions.recall_sessions(query, limit=limit)})


@mcp.tool()
def get_context_for_task(task: str, limit: int = 5) -> str:
    """Aggregate knowledge, code, sessions, errors and curriculum for a task."""
    return _json_result(context.get_context_for_task(task, limit=limit))


@mcp.tool()
def record_failure(context: str, error: str, fix: str = "") -> str:
    """Record a failure and correction for error-driven learning."""
    return _json_result(errors.record_failure(context, error, fix))


@mcp.tool()
def get_related_errors(query: str, limit: int = 5) -> str:
    """Find past failures related to a topic or task."""
    return _json_result({"query": query, "errors": errors.get_related_errors(query, limit=limit)})


@mcp.tool()
def add_concept_edge(from_concept: str, to_concept: str, relation: str = "relates_to") -> str:
    """Add an edge to the knowledge graph."""
    try:
        return _json_result(graph.add_edge(from_concept, to_concept, relation))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc)})


@mcp.tool()
def get_related_concepts(concept: str, depth: int = 2) -> str:
    """Traverse knowledge graph from a concept."""
    return _json_result(graph.get_related_concepts(concept, depth=depth))


@mcp.tool()
def suggest_learning(limit: int = 5) -> str:
    """Suggest topics Ravenna should study (active learning)."""
    return _json_result(active_learning.suggest_learning(limit=limit))


@mcp.tool()
def run_active_learning(max_items: int = 3) -> str:
    """Auto-learn weak areas and curriculum gaps via web search."""
    try:
        return _json_result(active_learning.run_active_learning(max_items=max_items))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc)})


@mcp.tool()
def export_training_data() -> str:
    """Export distillation pairs and notes as JSONL for fine-tuning."""
    return _json_result(finetune.export_training_data())


@mcp.tool()
def create_student_model(dry_run: bool = True) -> str:
    """Generate Ollama Modelfile and optionally create the raven model."""
    return _json_result(finetune.create_ollama_model(dry_run=dry_run))


@mcp.tool()
def learn_from_repo(url: str, tags: str = "github,repo") -> str:
    """Learn from a GitHub repository README and metadata."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        return _json_result(sources.learn_from_repo(url, tag_list))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "url": url})


@mcp.tool()
def learn_from_rss(feed_url: str, limit: int = 5) -> str:
    """Learn from RSS/Atom feed items."""
    try:
        return _json_result(sources.learn_from_rss(feed_url, limit=limit))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc), "feed_url": feed_url})


@mcp.tool()
def chat_with_ravenna(message: str, user_id: str = "mcp") -> str:
    """Conversational chat with Ravenna using local context and LLM."""
    try:
        return _json_result(chat.reply(message, channel="mcp", user_id=user_id))
    except Exception as exc:
        return _json_result({"success": False, "error": str(exc)})


def _run_theater_async(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("Theater MCP tools require sync MCP context; call via API REST.")


@mcp.tool()
def start_teaching_theater(
    max_cycles: int = 0,
    reset: bool = False,
    curriculum: str = "default",
) -> str:
    """Start observer. curriculum: default | remote-frontend | html-details-mastery | backend-mastery (24 ciclos)."""
    from learning_agent.core import theater

    from learning_agent.core.theater import TheaterHTTPError

    cycles = max_cycles if max_cycles > 0 else None
    try:
        result = _run_theater_async(
            theater.start_theater(max_cycles=cycles, reset=reset, curriculum=curriculum)
        )
    except TheaterHTTPError as exc:
        return _json_result(
            {"success": False, "error": exc.detail, "status_code": exc.status_code, **exc.extra}
        )
    return _json_result(result)


@mcp.tool()
def stop_teaching_theater() -> str:
    """Stop observer mode in Ravenna IDE."""
    from learning_agent.core import theater

    return _json_result(_run_theater_async(theater.stop_theater()))


@mcp.tool()
def post_theater_message(
    content: str,
    role: str = "cursor",
    agent: str = "Cursor Agent",
    level: str = "",
) -> str:
    """Post a message to Ravenna IDE observer panel (visible in real time)."""
    from learning_agent.core import theater

    return _json_result(
        _run_theater_async(
            theater.post_agent_message(role, agent, content, level=level)
        )
    )


@mcp.tool()
def get_theater_status() -> str:
    """Status of observer teaching mode (running, cycle, current track)."""
    from learning_agent.core import theater

    return _json_result(theater.get_status())


@mcp.tool()
def consolidate_learning(curriculum: str = "") -> str:
    """Full consolidation after observer session: progress, search, master note, quizzes by curriculum."""
    from learning_agent.core.consolidation import consolidate_full_session

    cur = curriculum if curriculum in ("default", "remote-frontend") else None
    return _json_result(consolidate_full_session(curriculum=cur))


@mcp.tool()
def create_ide_mastery_quiz() -> str:
    """Create complex quizzes testing ability to build full IDE (terminal, files, attachments, MCP)."""
    from learning_agent.core import ide_quiz

    return _json_result(ide_quiz.create_ide_mastery_quiz())


@mcp.tool()
def create_remoteapp_frontend_quiz() -> str:
    """Create complex RemoteApp Frontend quizzes (HTML, CSS, JS, Canvas, SVG, GSAP, architecture)."""
    
    return _json_result(remote_app_removed.create_remoteapp_frontend_quiz())


@mcp.tool()
def list_agents() -> str:
    """Lista agentes do projeto: subagentes Cursor, skills e registro em SQLite."""
    from learning_agent.core import agent_factory

    return _json_result(agent_factory.list_agents())


@mcp.tool()
def list_agent_archetypes() -> str:
    """Lista arquétipos disponíveis: backend, frontend, qa-inspector, data, custom."""
    from learning_agent.core import agent_factory

    return _json_result(agent_factory.list_archetypes())


@mcp.tool()
def scaffold_agent_project(
    name: str,
    archetype: str,
    description: str = "",
    focus: str = "",
    triggers: str = "",
    display_name: str = "",
    overwrite: bool = False,
) -> str:
    """Cria projeto completo de agente com aprendizado contínuo (manifest, playbook, subagente, skill)."""
    from learning_agent.core import agent_factory

    return _json_result(
        agent_factory.scaffold_agent_project(
            name,
            archetype,
            description,
            focus=focus,
            triggers=triggers,
            display_name=display_name,
            overwrite=overwrite,
        )
    )


@mcp.tool()
def scaffold_cursor_agent(
    name: str,
    description: str,
    focus: str,
    archetype: str = "custom",
    triggers: str = "Quando o usuário pedir ajuda neste domínio.",
    display_name: str = "",
    overwrite: bool = False,
) -> str:
    """Cria agente completo por arquétipo (backend, frontend, qa-inspector, data, custom)."""
    from learning_agent.core import agent_factory

    return _json_result(
        agent_factory.scaffold_cursor_agent(
            name,
            description,
            focus,
            archetype=archetype,
            triggers=triggers,
            display_name=display_name,
            overwrite=overwrite,
        )
    )


@mcp.tool()
def scaffold_skill(
    name: str,
    description: str,
    focus: str,
    triggers: str = "Quando o cenário descrito no skill se aplicar.",
    display_name: str = "",
    overwrite: bool = False,
) -> str:
    """Cria skill Cursor em .cursor/skills/{name}/SKILL.md."""
    from learning_agent.core import agent_factory

    return _json_result(
        agent_factory.scaffold_skill(
            name,
            description,
            focus,
            triggers=triggers,
            display_name=display_name,
            overwrite=overwrite,
        )
    )


@mcp.tool()
def validate_agent_definition(path: str) -> str:
    """Valida frontmatter e estrutura de .cursor/agents/*.md ou skills/*/SKILL.md."""
    from learning_agent.core import agent_factory

    return _json_result(agent_factory.validate_agent_definition(path))


@mcp.tool()
def agent_share_insight(
    from_agent: str,
    insight: str,
    topic: str,
    to_agents: str = "",
) -> str:
    """Agente compartilha descoberta com peers — aprendizado cruzado."""
    from learning_agent.core import agent_collaboration

    peers = [p.strip() for p in to_agents.split(",") if p.strip()] or None
    return _json_result(
        agent_collaboration.share_insight(from_agent, insight, topic, to_agents=peers)
    )


@mcp.tool()
def get_peer_insights(agent_name: str, limit: int = 10) -> str:
    """O que outros agentes compartilharam — para absorver antes de trabalhar."""
    from learning_agent.core import agent_collaboration

    return _json_result(agent_collaboration.get_peer_insights(agent_name, limit=limit))


@mcp.tool()
def detect_agent_gaps(agent_name: str, extra_topics: str = "") -> str:
    """Lacunas de conhecimento que o agente ainda não domina."""
    from learning_agent.core import agent_collaboration

    topics = [t.strip() for t in extra_topics.split(",") if t.strip()] or None
    return _json_result(
        agent_collaboration.detect_knowledge_gaps(agent_name, extra_topics=topics)
    )


@mcp.tool()
def agent_research_gaps(agent_name: str, max_topics: int = 3) -> str:
    """Pesquisa na web lacunas do agente e indexa + compartilha com peers."""
    from learning_agent.core import agent_collaboration

    return _json_result(
        agent_collaboration.agent_research_gaps(agent_name, max_topics=max_topics)
    )


@mcp.tool()
def run_agent_roundtable(
    topic: str,
    agents: str = "",
    max_rounds: int = 1,
) -> str:
    """Agentes conversam sobre um tópico e aprendem uns com os outros."""
    from learning_agent.core import agent_collaboration

    names = [a.strip() for a in agents.split(",") if a.strip()] or None
    return _json_result(
        agent_collaboration.run_agent_roundtable(topic, agents=names, max_rounds=max_rounds)
    )


@mcp.tool()
def consolidate_agent_ecosystem(agents: str = "", research_gaps: bool = True) -> str:
    """Consolida ecossistema: pesquisa, roundtable, nota mestra e quizzes."""
    from learning_agent.core import agent_collaboration

    names = [a.strip() for a in agents.split(",") if a.strip()] or None
    return _json_result(
        agent_collaboration.consolidate_agent_ecosystem(agents=names, research_gaps=research_gaps)
    )


@mcp.tool()
def ravenna_absorb_all_practices() -> str:
    """Ravenna absorve e consolida todas as práticas do ecossistema de agentes."""
    from learning_agent.core import agent_collaboration

    return _json_result(agent_collaboration.ravenna_absorb_all_practices())


@mcp.tool()
def run_peer_question_session(asker: str = "", answerer: str = "") -> str:
    """Agentes perguntam entre si o que o outro sabe — aprendizado cruzado."""
    from learning_agent.core import agent_autonomy

    return _json_result(
        agent_autonomy.run_peer_question_session(
            asker or None, answerer or None
        )
    )


@mcp.tool()
def agent_consult_ravenna(from_agent: str, question: str = "") -> str:
    """Agente consulta a Ravenna ativamente."""
    from learning_agent.core import agent_autonomy

    return _json_result(agent_autonomy.agent_consult_ravenna(from_agent, question))


@mcp.tool()
def agent_consult_teacher(from_agent: str, topic: str = "") -> str:
    """Agente consulta o professor (teacher API / distillation)."""
    from learning_agent.core import agent_autonomy

    return _json_result(agent_autonomy.agent_consult_teacher(from_agent, topic))


@mcp.tool()
def run_collab_dev_sprint(topic: str = "") -> str:
    """Sprint de desenvolvimento colaborativo — plano, testes e melhorias."""
    from learning_agent.core import agent_autonomy

    return _json_result(agent_autonomy.run_collab_dev_sprint(topic=topic))


@mcp.tool()
def run_autonomy_cycle_now() -> str:
    """Executa um ciclo autônomo completo: ação + closure (entender, testar, elevar)."""
    from learning_agent.core import agent_autonomy

    cycle = agent_autonomy.get_autonomy_status().get("cycle", 0) + 1
    return _json_result(agent_autonomy.run_autonomy_cycle(cycle))


@mcp.tool()
def list_autonomy_actions() -> str:
    """Lista todas as ações autônomas disponíveis no ecossistema."""
    from learning_agent.core import agent_autonomy, agent_learning_loop

    return _json_result(
        {
            "actions": agent_autonomy.AUTONOMY_ACTIONS,
            "closure_phases": list(agent_learning_loop.LEARNING_CLOSURE_PHASES),
        }
    )


@mcp.tool()
def run_autonomy_action(action: str, topic: str = "", agent: str = "") -> str:
    """Executa uma ação autônoma específica (peer_quiz, code_walk, proof_gate, etc.)."""
    from learning_agent.core import agent_autonomy, agent_learning_loop

    if action not in agent_autonomy.AUTONOMY_ACTIONS:
        return _json_result({"success": False, "error": f"ação inválida: {action}"})
    if action == "learning_closure":
        return _json_result(
            agent_learning_loop.run_learning_closure(
                topic or "manual", topic, {}, agent=agent or "ravenna"
            )
        )
    result = agent_autonomy.execute_autonomy_action(action, topic=topic)
    if result.get("success") is not False:
        result["learning_closure"] = agent_learning_loop.run_learning_closure(
            action, topic or str(result.get("topic", action)), result, agent=agent or ""
        )
    return _json_result(result)


@mcp.tool()
def run_peer_quiz(quizzer: str = "", target: str = "") -> str:
    """Quiz cruzado entre agentes — testar e elevar conhecimento."""
    from learning_agent.core import agent_learning_loop

    return _json_result(
        agent_learning_loop.run_peer_quiz(quizzer or None, target or None)
    )


@mcp.tool()
def run_error_roundtable() -> str:
    """Post-mortem colaborativo de erros recentes."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_error_roundtable())


@mcp.tool()
def run_code_walk(agent_name: str = "") -> str:
    """Agente explora código do projeto e compartilha lições."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_code_walk(agent_name or None))


@mcp.tool()
def run_weak_area_drill(agent_name: str = "") -> str:
    """Drill nas áreas fracas do progresso."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_weak_area_drill(agent_name or None))


@mcp.tool()
def run_proof_gate() -> str:
    """Portão de provas — health check do ecossistema."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_proof_gate())


@mcp.tool()
def run_execute_micro_sprint(topic: str = "") -> str:
    """Sprint executável com artefato Python e prova."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_execute_micro_sprint(topic=topic))


@mcp.tool()
def run_ravenna_hands_on(topic: str = "") -> str:
    """Ravenna coloca a mão na massa: indexa, planeja e valida."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_ravenna_hands_on(topic=topic))


@mcp.tool()
def run_learning_closure(action: str, topic: str = "", agent: str = "ravenna") -> str:
    """Fase obrigatória: entender → testar → elevar após qualquer aprendizado."""
    from learning_agent.core import agent_learning_loop

    return _json_result(
        agent_learning_loop.run_learning_closure(action, topic, {}, agent=agent)
    )


@mcp.tool()
def get_agent_curriculum(agent: str = "") -> str:
    """Currículo e próximo marco até nível 5."""
    from learning_agent.core import agent_curriculum

    if agent.strip():
        return _json_result(agent_curriculum.get_next_milestone(agent.strip()))
    return _json_result(agent_curriculum.list_curricula())


@mcp.tool()
def run_mentor_session(mentor: str = "", mentee: str = "") -> str:
    """Sessão de mentoria fixa entre agentes."""
    from learning_agent.core import agent_mentoring

    return _json_result(
        agent_mentoring.run_mentor_session(mentor or None, mentee or None)
    )


@mcp.tool()
def run_spaced_review(agent: str = "") -> str:
    """Revisão espaçada SM-2 do domínio do agente."""
    from learning_agent.core import agent_spaced_review

    return _json_result(agent_spaced_review.run_spaced_review(agent or None))


@mcp.tool()
def run_ide_improvement_sprint(agent: str = "") -> str:
    """Agente propõe melhorias na Ravenna IDE no seu domínio."""
    from learning_agent.core import agent_ide_practice

    return _json_result(agent_ide_practice.run_ide_improvement_sprint(agent or None))


@mcp.tool()
def get_software_excellence_status() -> str:
    """Objetivo norte — fábrica de software de excelência (IDE é aula prática)."""
    from learning_agent.core import software_excellence

    return _json_result(software_excellence.assess_excellence())


@mcp.tool()
def run_software_excellence_sprint() -> str:
    """Sprint no próximo gap da fábrica de software de excelência."""
    from learning_agent.core import software_excellence

    return _json_result(software_excellence.run_software_excellence_sprint())


@mcp.tool()
def run_brain_pipeline(dry_run: bool = False) -> str:
    """Exporta treino, gera Modelfile e cria o modelo raven no Ollama."""
    from learning_agent.core import software_excellence

    return _json_result(software_excellence.run_brain_pipeline(dry_run=dry_run))


@mcp.tool()
def get_raven_readiness_status() -> str:
    """Preparação total da Raven — fases, corpus, modelo e L6."""
    from learning_agent.core import raven_readiness

    return _json_result(raven_readiness.assess_readiness())


@mcp.tool()
def run_raven_preparation_sprint() -> str:
    """Próximo passo do roteiro até a Raven ficar totalmente preparada."""
    from learning_agent.core import raven_readiness

    return _json_result(raven_readiness.run_preparation_sprint())


@mcp.tool()
def run_distillation_batch(target_pairs: int = 20, max_topics: int = 0) -> str:
    """Destilação em massa — professor API ensina aluno local até corpus mínimo."""
    from learning_agent.core import software_excellence

    return _json_result(
        software_excellence.run_distillation_batch(
            target_pairs=target_pairs,
            max_topics=max_topics or None,
            broadcast_observer=True,
        )
    )


@mcp.tool()
def get_ide_completion_status(full: bool = False) -> str:
    """Aula prática — paridade Cursor + frontend impecável (100% = IDE concluída)."""
    from learning_agent.core import ide_objectives

    return _json_result(ide_objectives.assess_completion(run_slow_probes=full))


@mcp.tool()
def run_ide_completion_sprint() -> str:
    """Sprint no próximo gap de paridade Cursor."""
    from learning_agent.core import ide_objectives

    return _json_result(ide_objectives.run_ide_completion_sprint())


@mcp.tool()
def get_model_parity(agent: str = "") -> str:
    """Paridade cognitiva — conhecimento, raciocínio e decisão vs modelos de referência."""
    from learning_agent.core import agent_model_parity

    if agent.strip():
        return _json_result(agent_model_parity.get_agent_parity(agent.strip()))
    return _json_result(agent_model_parity.assess_ecosystem_parity())


@mcp.tool()
def run_model_parity_assessment(agent: str = "") -> str:
    """Benchmark cognitivo do agente (nível 6 / paridade com modelos do plano)."""
    from learning_agent.core import agent_model_parity
    from learning_agent.core.agent_capability import CORE_AGENTS

    slug = agent.strip() or CORE_AGENTS[0]
    return _json_result(agent_model_parity.run_model_parity_assessment(slug))


@mcp.tool()
def run_strict_parity_assessment(agent: str = "") -> str:
    """Benchmark L6 exigente (juiz professor, RAG, prova real) — tier Cursor."""
    from learning_agent.core import agent_model_parity
    from learning_agent.core.agent_capability import CORE_AGENTS

    slug = agent.strip() or CORE_AGENTS[0]
    return _json_result(agent_model_parity.run_strict_parity_assessment(slug))


@mcp.tool()
def get_finance_lead_training_status() -> str:
    """Status de treino finance-lead — currículo, Prove, paridade L6 (qualidade)."""
    from learning_agent.core import finance_lead_engine

    return _json_result(finance_lead_engine.build_training_status())


@mcp.tool()
def run_finance_lead_quality_cycle(dimension: str = "decision") -> str:
    """Ciclo completo finance-lead: web + Cursor proxy + estudo + prática + currículo."""
    from learning_agent.core import finance_lead_engine

    return _json_result(
        finance_lead_engine.run_quality_cycle(cycle_n=1, dimension=dimension.strip() or "decision")
    )


@mcp.tool()
def run_cursor_mentor_session(agent: str, dimension: str = "decision") -> str:
    """Mentor Cursor destila lição focada na dimensão fraca do agente."""
    from learning_agent.core import cursor_mentor

    return _json_result(cursor_mentor.run_cursor_mentor_session(agent, dimension))


@mcp.tool()
def run_l6_refinement(agent: str = "") -> str:
    """Refina agente(s) até L6 strict — mentor Cursor + pares + re-avaliação."""
    from learning_agent.core import l6_refinement

    if agent.strip():
        return _json_result(l6_refinement.refine_agent_to_l6(agent.strip(), max_rounds=2))
    return _json_result(l6_refinement.refine_all_core_agents(max_rounds=2))


@mcp.tool()
def run_agent_study_session(agent: str = "", full_verify: bool = True) -> str:
    """Sessão de estudo estruturado: diagnosticar → Cursor → par → prática → prova → destilar."""
    from learning_agent.core import agent_study_methodology

    if agent.strip():
        return _json_result(
            agent_study_methodology.run_study_session(
                agent.strip(), broadcast_observer=False, full_verify=full_verify
            )
        )
    return _json_result(agent_study_methodology.run_ecosystem_study_round(broadcast_observer=False))


@mcp.tool()
def emit_autonomy_event(event_type: str, detail: str = "", agent: str = "", path: str = "") -> str:
    """Dispara gatilho de evento para autonomia reativa."""
    from learning_agent.core import agent_event_triggers

    return _json_result(
        agent_event_triggers.emit_event(event_type, detail=detail, agent=agent, path=path)
    )


@mcp.tool()
def get_agent_evolution(agent: str = "") -> str:
    """Níveis de capacidade 1–5 — critérios de Especialista e próximas ações."""
    from learning_agent.core import agent_capability

    if agent.strip():
        return _json_result(agent_capability.compute_agent_capability(agent.strip()))
    return _json_result(agent_capability.assess_ecosystem())


@mcp.tool()
def run_debug_sweep() -> str:
    """Reliability Lead — varredura de debug com proof_gate e erros relacionados."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_debug_sweep())


@mcp.tool()
def run_agent_health_audit() -> str:
    """Reliability Lead — auditoria de registry, órfãos e autonomia."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_agent_health_audit())


@mcp.tool()
def run_optimize_cycle() -> str:
    """Reliability Lead — otimizações do ciclo autônomo com base em métricas."""
    from learning_agent.core import agent_learning_loop

    return _json_result(agent_learning_loop.run_optimize_cycle())


def main() -> None:
    transport = "stdio"
    port = MCP_HTTP_PORT

    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--transport" and i + 2 < len(sys.argv):
            transport = sys.argv[i + 2]
        if arg == "--port" and i + 2 < len(sys.argv):
            port = int(sys.argv[i + 2])

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
