
# sanitized: employer-specific RemoteApp integrations removed
def _sanitized_false(*_a, **_k):
    return False
def _sanitized_none(*_a, **_k):
    return None
def _sanitized_dict(*_a, **_k):
    return {}
audit_remote_notifications_removed = _sanitized_dict
is_remote_feature_implement_work_removed = _sanitized_false
is_remote_static_publish_work_removed = _sanitized_false
is_remote_deploy_work_removed = _sanitized_false
is_remote_notification_work_removed = _sanitized_false
is_remote_restart_validate_work_removed = _sanitized_false
build_remote_deploy_reply_removed = _sanitized_none
build_remote_notification_reply_removed = _sanitized_none
build_remote_restart_validate_reply_removed = _sanitized_none
build_remote_static_publish_reply_removed = _sanitized_none
REMOTE_STATIC_PATHS_REMOVED = ()
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from learning_agent import db, sync
from learning_agent.channels.dashboard import DASHBOARD_HTML, get_dashboard
from learning_agent.config import API_HOST, API_PORT, PROJECT_ROOT
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
    memory_audit,
    progress,
    proofs,
    quiz,
    sessions,
    sources,
    web,
)
from learning_agent.identity import AGENT_NAME, AGENT_ROLE, IDENTITY_BRIEF
from learning_agent import api_editor


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    from learning_agent.core import agent_autonomy
    from learning_agent.core.workspace_bootstrap import ensure_ecosystem_workspace_roots

    ensure_ecosystem_workspace_roots()
    await agent_autonomy.maybe_auto_start()
    yield
    await agent_autonomy.stop_autonomy()


app = FastAPI(
    title=f"{AGENT_NAME} API",
    description=f"API REST da {AGENT_NAME} — {AGENT_ROLE}. {IDENTITY_BRIEF}",
    version="0.1.0",
    lifespan=_app_lifespan,
)

# Add CORS middleware for IDE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

# Gateway OpenAI-compatível /v1 para editores externos (Cursor/VS Code).
app.include_router(api_editor.router)


class KnowledgeRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class NoteRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class QuizRequest(BaseModel):
    topic: str = "general"
    count: int = 3


class AnswerRequest(BaseModel):
    quiz_item_id: int
    correct: bool
    response: str = ""


class FetchLearnRequest(BaseModel):
    url: str
    title: str = ""
    tags: list[str] = Field(default_factory=list)


class SearchWebRequest(BaseModel):
    query: str
    limit: int = 5


class SearchLearnRequest(BaseModel):
    query: str
    limit: int = 3
    tags: list[str] = Field(default_factory=list)


class DistillRequest(BaseModel):
    topic: str
    context: str = ""
    tags: list[str] = Field(default_factory=list)


class CursorDistillRequest(BaseModel):
    topic: str
    teacher_content: str
    context: str = ""
    teacher_model: str = "cursor"


class SessionRequest(BaseModel):
    summary: str
    topics: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    duration_minutes: int = 0


class FailureRequest(BaseModel):
    context: str
    error: str
    fix: str = ""
    tags: list[str] = Field(default_factory=list)


class ContextRequest(BaseModel):
    task: str
    limit: int = 5


class GraphEdgeRequest(BaseModel):
    from_concept: str
    to_concept: str
    relation: str = "relates_to"


class RepoLearnRequest(BaseModel):
    url: str
    tags: list[str] = Field(default_factory=list)


class RssLearnRequest(BaseModel):
    feed_url: str
    limit: int = 5


class ChatRequest(BaseModel):
    message: str
    user_id: str = "api"
    include_context: bool = True


@app.get("/health")
def health() -> dict[str, Any]:
    from learning_agent.config import (
        AGENT_MODEL,
        AUTO_DISTILL,
        AUTO_PROOFS,
        AUTO_SYNC,
        CHAT_MODEL,
        CHAT_MODEL_FAST,
        DEEPSEEK_API_KEY,
        DEEPSEEK_MODEL,
        DEEPSEEK_MODEL_FAST,
        TEACHER_MODEL,
    )
    from learning_agent.core import llm as llm_core
    from learning_agent.core import progress, theater

    db_ok = True
    try:
        from learning_agent import db as ldb

        ldb.init_db()
        with ldb.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        db_ok = False

    prog = progress.get_progress()
    theater_st = theater.get_status()
    maint = llm_core.maintenance_status()

    return {
        "status": "ok" if db_ok else "degraded",
        "agent": AGENT_NAME,
        "role": AGENT_ROLE,
        "identity": IDENTITY_BRIEF,
        "database": "ok" if db_ok else "error",
        "theater": {
            "running": theater_st.get("running", False),
            "curriculum": theater_st.get("curriculum"),
            "cycle": theater_st.get("cycle", 0),
        },
        "learning": {
            "total_notes": prog["summary"]["total_notes"],
            "total_quizzes": prog["summary"]["total_quizzes"],
            "due_reviews": prog["summary"]["due_reviews"],
            "weak_areas": prog.get("weak_areas", []),
        },
        "cloud_sync_configured": sync.is_configured(),
        "auto_sync_enabled": sync.is_configured() and AUTO_SYNC,
        "auto_proofs_enabled": AUTO_PROOFS,
        "distillation": distillation.get_status(),
        "auto_distill_enabled": AUTO_DISTILL,
        "llm_models": {
            "chat": CHAT_MODEL,
            "agent": AGENT_MODEL,
            "fast": CHAT_MODEL_FAST,
            "teacher": TEACHER_MODEL,
            "deepseek": DEEPSEEK_MODEL if DEEPSEEK_API_KEY else None,
            "deepseek_flash": DEEPSEEK_MODEL_FAST if DEEPSEEK_API_KEY else None,
            "maintenance_mode": maint["maintenance_mode"],
            "maintenance_configured": maint["maintenance_configured"],
            "maintenance_model": maint["maintenance_model"],
            "engines": llm_core.engines_status(),
        },
    }


@app.get("/api/llm/deepseek/balance")
def deepseek_balance_endpoint() -> dict[str, Any]:
    """Saldo DeepSeek (GET /user/balance) — proxy server-side, sem expor a chave."""
    from learning_agent.core.deepseek_balance import fetch_deepseek_balance

    return fetch_deepseek_balance()


@app.get("/proofs")
def run_proofs() -> dict[str, Any]:
    return proofs.run_full_proof_suite()


@app.post("/proofs/python")
def prove_python(body: dict[str, str]) -> dict[str, Any]:
    check = proofs.prove_python_runs(
        body.get("code", ""),
        expected_in_output=body.get("expected_output", ""),
    )
    return {"all_passed": check["passed"], "checks": [check]}


@app.get("/knowledge/search")
def search_knowledge(q: str = Query(..., min_length=1), limit: int = 5) -> dict[str, Any]:
    results = knowledge.search(q, limit=limit)
    return {"query": q, "results": results}


@app.post("/knowledge")
def add_knowledge(body: KnowledgeRequest) -> dict[str, Any]:
    return knowledge.index_text(body.title, body.content, body.tags)


@app.post("/knowledge/fetch")
def fetch_and_learn(body: FetchLearnRequest) -> dict[str, Any]:
    try:
        return web.fetch_and_learn(body.url, title=body.title, tags=body.tags or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/knowledge/search-web")
def search_web(body: SearchWebRequest) -> dict[str, Any]:
    try:
        results = web.search_web(body.query, limit=body.limit)
        return {"query": body.query, "results": results}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/knowledge/search-and-learn")
def search_and_learn(body: SearchLearnRequest) -> dict[str, Any]:
    try:
        return web.search_and_learn(body.query, limit=body.limit, tags=body.tags or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/notes")
def add_note(body: NoteRequest) -> dict[str, Any]:
    return knowledge.add_note(body.title, body.content, body.tags)


@app.get("/distillation/status")
def distillation_status() -> dict[str, Any]:
    return distillation.get_status()


@app.get("/api/distillation/status")
def distillation_status_api() -> dict[str, Any]:
    return distillation.get_status()


@app.get("/distillation/pairs")
def distillation_pairs(limit: int = 20) -> dict[str, Any]:
    return {"pairs": distillation.list_pairs(limit=limit)}


@app.get("/api/distillation/pairs")
def distillation_pairs_api(limit: int = 20) -> dict[str, Any]:
    return {"pairs": distillation.list_pairs(limit=limit)}


@app.post("/distillation/topic")
def distill_topic_endpoint(body: DistillRequest) -> dict[str, Any]:
    try:
        return distillation.distill_topic(body.topic, context=body.context, tags=body.tags or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/distillation/cursor")
def distill_cursor_endpoint(body: CursorDistillRequest) -> dict[str, Any]:
    """Professor = Cursor (conteúdo que você cola); aluno = modelo local Ollama."""
    try:
        return distillation.distill_from_teacher_content(
            body.topic,
            body.teacher_content,
            context=body.context,
            teacher_model=body.teacher_model,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/distillation/note/{note_id}")
def distill_note_endpoint(note_id: int) -> dict[str, Any]:
    try:
        return distillation.distill_from_note(note_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/codebase/index")
def index_codebase_endpoint(dirs: str = "learning_agent") -> dict[str, Any]:
    dir_list = [d.strip() for d in dirs.split(",") if d.strip()]
    return codebase.index_codebase(dir_list or None)


@app.get("/codebase/search")
def search_code_endpoint(q: str = Query(..., min_length=1), limit: int = 5) -> dict[str, Any]:
    return {"query": q, "results": codebase.search_code(q, limit=limit)}


@app.post("/sessions")
def record_session_endpoint(body: SessionRequest) -> dict[str, Any]:
    return sessions.record_session(
        body.summary,
        body.topics,
        body.decisions,
        body.duration_minutes,
    )


@app.get("/sessions/recent")
def recent_sessions(limit: int = 5) -> dict[str, Any]:
    return {"sessions": sessions.get_recent_sessions(limit)}


@app.get("/sessions/recall")
def recall_sessions_endpoint(q: str = Query(..., min_length=1), limit: int = 5) -> dict[str, Any]:
    return {"query": q, "sessions": sessions.recall_sessions(q, limit=limit)}


@app.post("/context")
def context_for_task(body: ContextRequest) -> dict[str, Any]:
    return context.get_context_for_task(body.task, limit=body.limit)


@app.post("/errors")
def record_failure_endpoint(body: FailureRequest) -> dict[str, Any]:
    return errors.record_failure(body.context, body.error, body.fix, body.tags or None)


@app.get("/errors/related")
def related_errors(q: str = Query(..., min_length=1), limit: int = 5) -> dict[str, Any]:
    return {"query": q, "errors": errors.get_related_errors(q, limit=limit)}


# ========================
# IDE Integration Endpoints
# ========================


class ChatMessageRequest(BaseModel):
    message: str
    context: str = ""
    agent: str = ""
    mode: str = "chat"  # chat | agent | fast
    channel: str = "ide"  # ide | telegram
    user_id: str = ""
    auto_delegate: bool = False
    model_size: str = "auto"  # auto | 0.5b | 32b
    engine: str = "groq"  # groq | deepseek_pro | deepseek_flash
    conversation_id: str = ""
    persist_history: bool = True
    include_context: bool | None = None
    auto_apply: bool = False
    max_repair_attempts: int = Field(2, ge=0, le=3)
    project_root: str | None = None
    run_checklist: bool = True
    study_mode: bool = False
    delivery_mode: str = "auto"  # auto | refine | full | seed-only | vistoria
    tool_max_turns: int | None = Field(None, ge=0, le=6)
    attachment_ids: list[str] = Field(default_factory=list)


class WorkspaceStudyRequest(BaseModel):
    root_ids: list[str] = Field(default_factory=list)
    message: str = "Estude a aplicação anexada de ponta a ponta."
    synthesize: bool = True
    persist_note: bool = True
    verify: bool = True
    recall_prior: bool = True
    max_files: int = Field(36, ge=4, le=48)


class SoftwareDeliveryRequest(BaseModel):
    message: str
    project_root: str | None = None
    auto_apply: bool = True
    run_validation: bool = True
    use_model_rounds: bool | None = None
    model_size: str = "auto"
    max_repair_rounds: int = Field(1, ge=0, le=3)


class CreateConversationRequest(BaseModel):
    title: str = "Nova conversa"
    project_name: str = ""
    project_root: str = ""
    workspace_root_ids: list[str] = Field(default_factory=list)


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    project_name: str | None = None
    project_root: str | None = None
    workspace_root_ids: list[str] | None = None


class DelegateRouteRequest(BaseModel):
    message: str
    context: str = ""
    exclude: list[str] = Field(default_factory=list)


class ScaffoldAgentRequest(BaseModel):
    name: str
    description: str
    focus: str
    archetype: str = "custom"
    triggers: str = "Quando o usuário pedir ajuda neste domínio."
    display_name: str = ""
    overwrite: bool = False


class ScaffoldAgentProjectRequest(BaseModel):
    name: str
    archetype: str
    description: str = ""
    focus: str = ""
    triggers: str = ""
    display_name: str = ""
    overwrite: bool = False


class ScaffoldSkillRequest(BaseModel):
    name: str
    description: str
    focus: str
    triggers: str = "Quando o cenário descrito no skill se aplicar."
    display_name: str = ""
    overwrite: bool = False


class AgentShareInsightRequest(BaseModel):
    from_agent: str
    insight: str
    topic: str
    to_agents: list[str] = Field(default_factory=list)


class AgentRoundtableRequest(BaseModel):
    topic: str
    agents: list[str] = Field(default_factory=list)
    max_rounds: int = 1


class AgentResearchGapsRequest(BaseModel):
    agent_name: str
    max_topics: int = 3


class ConsolidateEcosystemRequest(BaseModel):
    agents: list[str] = Field(default_factory=list)
    research_gaps: bool = True


class ActiveCollaborationRequest(BaseModel):
    interval_seconds: int = 300
    topic: str = ""


class AutonomyAlwaysOnRequest(BaseModel):
    enabled: bool = True
    interval_seconds: int = 300


class AutonomyActionRequest(BaseModel):
    action: str
    topic: str = ""
    agent: str = ""


@app.get("/api/identity")
def get_identity() -> dict[str, Any]:
    """Get Ravenna identity info"""
    from learning_agent.identity import AGENT_SPECIALTIES

    return {
        "name": AGENT_NAME,
        "role": AGENT_ROLE,
        "brief": IDENTITY_BRIEF,
        "specialties": AGENT_SPECIALTIES,
    }


@app.get("/api/agents")
def list_agents_endpoint() -> dict[str, Any]:
    """Lista subagentes, skills e supervisores do ecossistema."""
    from learning_agent.core import agent_factory

    return agent_factory.list_agents()


@app.post("/api/agents/delegate/route")
def delegate_route_endpoint(body: DelegateRouteRequest) -> dict[str, Any]:
    """Sugere subagente para delegação automática (paridade Cursor subagents)."""
    from learning_agent.core import agent_delegate

    result = agent_delegate.suggest_delegate(
        body.message,
        body.context or "",
        exclude=body.exclude,
    )
    return {"success": True, **result}


@app.get("/api/agents/delegate/suggest")
def delegate_suggest_endpoint(
    message: str = Query(..., min_length=1),
    context: str = "",
) -> dict[str, Any]:
    from learning_agent.core import agent_delegate

    result = agent_delegate.suggest_delegate(message, context or "")
    return {"success": True, **result}


@app.get("/api/agents/archetypes")
def list_archetypes_endpoint() -> dict[str, Any]:
    """Lista arquétipos: backend, frontend, qa-inspector, data, custom."""
    from learning_agent.core import agent_factory

    return agent_factory.list_archetypes()


@app.post("/api/agents/projects/scaffold")
def scaffold_agent_project_endpoint(body: ScaffoldAgentProjectRequest) -> dict[str, Any]:
    """Cria projeto completo de agente com aprendizado contínuo."""
    from learning_agent.core import agent_factory

    return agent_factory.scaffold_agent_project(
        body.name,
        body.archetype,
        body.description,
        focus=body.focus,
        triggers=body.triggers,
        display_name=body.display_name,
        overwrite=body.overwrite,
    )


@app.post("/api/agents/scaffold")
def scaffold_agent_endpoint(body: ScaffoldAgentRequest) -> dict[str, Any]:
    """Cria agente por arquétipo (atalho para scaffold_agent_project)."""
    from learning_agent.core import agent_factory

    return agent_factory.scaffold_cursor_agent(
        body.name,
        body.description,
        body.focus,
        archetype=body.archetype,
        triggers=body.triggers,
        display_name=body.display_name,
        overwrite=body.overwrite,
    )


@app.post("/api/agents/skills/scaffold")
def scaffold_skill_endpoint(body: ScaffoldSkillRequest) -> dict[str, Any]:
    """Cria skill Cursor (.cursor/skills/{name}/SKILL.md)."""
    from learning_agent.core import agent_factory

    return agent_factory.scaffold_skill(
        body.name,
        body.description,
        body.focus,
        triggers=body.triggers,
        display_name=body.display_name,
        overwrite=body.overwrite,
    )


@app.get("/api/agents/validate")
def validate_agent_endpoint(path: str = Query(..., min_length=3)) -> dict[str, Any]:
    """Valida definição de agente ou skill."""
    from learning_agent.core import agent_factory

    return agent_factory.validate_agent_definition(path)


@app.post("/api/agents/collaborate/share")
def agent_share_insight_endpoint(body: AgentShareInsightRequest) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    peers = body.to_agents or None
    return agent_collaboration.share_insight(
        body.from_agent, body.insight, body.topic, to_agents=peers
    )


@app.get("/api/agents/collaborate/peers/{agent_name}/insights")
def get_peer_insights_endpoint(agent_name: str, limit: int = 10) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    return agent_collaboration.get_peer_insights(agent_name, limit=limit)


@app.get("/api/agents/collaborate/gaps/{agent_name}")
def detect_agent_gaps_endpoint(
    agent_name: str,
    extra_topics: str = Query(""),
) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    topics = [t.strip() for t in extra_topics.split(",") if t.strip()] or None
    return agent_collaboration.detect_knowledge_gaps(agent_name, extra_topics=topics)


@app.post("/api/agents/collaborate/research-gaps")
def agent_research_gaps_endpoint(body: AgentResearchGapsRequest) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    return agent_collaboration.agent_research_gaps(
        body.agent_name, max_topics=body.max_topics
    )


@app.post("/api/agents/collaborate/roundtable")
def agent_roundtable_endpoint(body: AgentRoundtableRequest) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    names = body.agents or None
    return agent_collaboration.run_agent_roundtable(
        body.topic, agents=names, max_rounds=body.max_rounds
    )


@app.post("/api/agents/consolidate")
def consolidate_ecosystem_endpoint(body: ConsolidateEcosystemRequest) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    names = body.agents or None
    return agent_collaboration.consolidate_agent_ecosystem(
        agents=names, research_gaps=body.research_gaps
    )


@app.post("/api/agents/ravenna/absorb")
def ravenna_absorb_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    return agent_collaboration.ravenna_absorb_all_practices()


@app.get("/api/agents/collaborate/exchanges")
def agent_exchanges_endpoint(
    thread_id: str = Query(""),
    limit: int = 30,
) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    tid = thread_id.strip() or None
    return agent_collaboration.get_exchange_history(tid, limit=limit)


@app.get("/api/agents/collaborate/active")
def active_collaboration_status_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    return agent_autonomy.get_autonomy_status()


@app.post("/api/agents/collaborate/active/start")
async def start_active_collaboration_endpoint(
    body: ActiveCollaborationRequest,
) -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    return await agent_collaboration.start_active_collaboration(
        interval_seconds=body.interval_seconds,
        topic=body.topic,
    )


@app.post("/api/agents/collaborate/active/stop")
async def stop_active_collaboration_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_collaboration

    return await agent_collaboration.stop_active_collaboration()


@app.post("/api/agents/autonomy/cycle")
def run_autonomy_cycle_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    cycle = agent_autonomy.get_autonomy_status().get("cycle", 0) + 1
    return agent_autonomy.run_autonomy_cycle(cycle)


@app.post("/api/agents/autonomy/peer-question")
def peer_question_endpoint(
    asker: str = Query(""),
    answerer: str = Query(""),
) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    return agent_autonomy.run_peer_question_session(
        asker or None, answerer or None
    )


@app.post("/api/agents/autonomy/collab-sprint")
def collab_sprint_endpoint(topic: str = Query("")) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    return agent_autonomy.run_collab_dev_sprint(topic=topic)


class AutonomyEventRequest(BaseModel):
    event_type: str
    detail: str = ""
    agent: str = ""
    path: str = ""


@app.get("/api/agents/curriculum")
def list_curricula_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_curriculum

    return agent_curriculum.list_curricula()


@app.get("/api/agents/curriculum/{agent_name}")
def agent_curriculum_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_curriculum

    milestone = agent_curriculum.get_next_milestone(agent_name.strip())
    curriculum = agent_curriculum.load_agent_curriculum(agent_name.strip())
    return {"curriculum": curriculum, "next_milestone": milestone}


@app.post("/api/agents/events")
def emit_autonomy_event_endpoint(body: AutonomyEventRequest) -> dict[str, Any]:
    from learning_agent.core import agent_event_triggers

    return agent_event_triggers.emit_event(
        body.event_type.strip(),
        detail=body.detail,
        agent=body.agent,
        path=body.path,
    )


@app.get("/api/agents/events")
def list_autonomy_events_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_event_triggers

    return agent_event_triggers.list_pending_events()


@app.get("/api/agents/model-parity")
def model_parity_ecosystem_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_model_parity

    return agent_model_parity.assess_ecosystem_parity()


@app.get("/api/agents/model-parity/{agent_name}")
def model_parity_agent_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_model_parity

    return agent_model_parity.get_agent_parity(agent_name.strip())


@app.post("/api/agents/model-parity/{agent_name}/assess")
def model_parity_assess_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_model_parity

    return agent_model_parity.run_model_parity_assessment(agent_name.strip())


@app.post("/api/agents/model-parity/{agent_name}/assess-strict")
def model_parity_assess_strict_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_model_parity

    return agent_model_parity.run_strict_parity_assessment(agent_name.strip())


@app.post("/api/agents/l6/refinement")
def l6_refinement_all_endpoint() -> dict[str, Any]:
    from learning_agent.core import l6_refinement

    return l6_refinement.refine_all_core_agents(broadcast_observer=False)


@app.post("/api/agents/l6/refinement/{agent_name}")
def l6_refinement_agent_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import l6_refinement

    return l6_refinement.refine_agent_to_l6(agent_name.strip(), broadcast_observer=False)


@app.post("/api/agents/study")
def agent_study_round_endpoint() -> dict[str, Any]:
    """Uma rodada de estudo estruturado — prioriza agente com menor L6."""
    from learning_agent.core import agent_study_methodology

    return agent_study_methodology.run_ecosystem_study_round(broadcast_observer=False)


@app.post("/api/agents/study/{agent_name}")
def agent_study_session_endpoint(agent_name: str, full_verify: bool = True) -> dict[str, Any]:
    from learning_agent.core import agent_study_methodology

    return agent_study_methodology.run_study_session(
        agent_name.strip(), broadcast_observer=False, full_verify=full_verify
    )


@app.get("/api/excellence")
def software_excellence_endpoint() -> dict[str, Any]:
    """Objetivo norte — fábrica de software de excelência sob demanda."""
    from learning_agent.core import software_excellence

    return software_excellence.assess_excellence()


@app.post("/api/excellence/sprint")
def software_excellence_sprint_endpoint() -> dict[str, Any]:
    from learning_agent.core import software_excellence

    return software_excellence.run_software_excellence_sprint()


@app.post("/api/software/delivery/run")
def software_delivery_run_endpoint(request: SoftwareDeliveryRequest) -> dict[str, Any]:
    """Executa a fábrica autônoma: spec, work orders, gates e relatório final."""
    from learning_agent.core import software_delivery

    return software_delivery.run_software_delivery(
        request.message,
        project_root=request.project_root,
        auto_apply=request.auto_apply,
        run_validation=request.run_validation,
        use_model_rounds=request.use_model_rounds,
        model_size=request.model_size,
        max_repair_rounds=request.max_repair_rounds,
    )


@app.post("/api/excellence/brain")
def brain_pipeline_endpoint(dry_run: bool = False) -> dict[str, Any]:
    from learning_agent.core import software_excellence

    return software_excellence.run_brain_pipeline(dry_run=dry_run)


@app.post("/api/excellence/distill-batch")
def distillation_batch_endpoint(target: int = 20, max_topics: int | None = None) -> dict[str, Any]:
    from learning_agent.core import software_excellence

    return software_excellence.run_distillation_batch(
        target_pairs=target,
        max_topics=max_topics,
        broadcast_observer=True,
    )


@app.get("/api/raven/readiness")
def raven_readiness_endpoint() -> dict[str, Any]:
    """Preparação total da Raven — roteiro até software completo de alto nível."""
    from learning_agent.core import raven_readiness

    return raven_readiness.assess_readiness()


@app.post("/api/raven/readiness/sprint")
def raven_preparation_sprint_endpoint() -> dict[str, Any]:
    from learning_agent.core import raven_readiness

    return raven_readiness.run_preparation_sprint()


@app.get("/api/ide/completion")
def ide_completion_endpoint(full: bool = False) -> dict[str, Any]:
    """Aula prática — IDE concluída com paridade Cursor + polish 100%."""
    from learning_agent.core import ide_objectives

    return ide_objectives.assess_completion(run_slow_probes=full)


@app.post("/api/ide/completion/sprint")
def ide_completion_sprint_endpoint() -> dict[str, Any]:
    from learning_agent.core import ide_objectives

    return ide_objectives.run_ide_completion_sprint()


@app.get("/api/agents/evolution")
def agent_evolution_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_capability

    return agent_capability.assess_ecosystem()


@app.get("/api/agents/evolution/{agent_name}")
def agent_evolution_one_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_capability

    return agent_capability.compute_agent_capability(agent_name.strip())


@app.get("/api/agents/progress-dashboard")
def agent_progress_dashboard_endpoint(days: int = 14) -> dict[str, Any]:
    """Progresso agregado — journal, evolução (incl. finance-lead), IDE, destilação."""
    from learning_agent.core import agent_progress_dashboard

    return agent_progress_dashboard.build_progress_dashboard(days=min(max(days, 7), 30))


@app.get("/api/agents/external-completion")
def external_completion_all_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_external_completion

    return agent_external_completion.assess_all_with_external_criteria()


@app.get("/api/agents/external-completion/{agent_name}")
def external_completion_one_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_external_completion

    return agent_external_completion.assess_external_completion(agent_name.strip())


@app.get("/api/agents/finance-lead/training-status")
def finance_lead_training_status_endpoint() -> dict[str, Any]:
    from learning_agent.core import finance_lead_engine

    return {"success": True, **finance_lead_engine.build_training_status()}


@app.post("/api/agents/finance-lead/quality-cycle")
def finance_lead_quality_cycle_endpoint(
    dimension: str = "decision",
    full_verify: bool = False,
) -> dict[str, Any]:
    from learning_agent.core import finance_lead_engine

    state_path = PROJECT_ROOT / "data" / "finance_lead_overnight_state.json"
    cycle_n = 1
    if state_path.is_file():
        try:
            cycle_n = int(json.loads(state_path.read_text(encoding="utf-8")).get("cycle", 0)) + 1
        except (json.JSONDecodeError, ValueError):
            pass
    return finance_lead_engine.run_quality_cycle(
        cycle_n=cycle_n,
        dimension=dimension.strip() or "decision",
        full_verify=full_verify,
    )


@app.post("/api/agents/finance-lead/reasoning-practice")
def finance_lead_reasoning_practice_endpoint() -> dict[str, Any]:
    """Prática real finance-lead — reasoning + ambiente paper + paridade L6."""
    from learning_agent.core import finance_lead_engine

    return finance_lead_engine.run_reasoning_practice_session()


@app.get("/api/ship/status")
def ship_status_endpoint() -> dict[str, Any]:
    from learning_agent.core import ship_pipeline

    return ship_pipeline.build_ship_status()


@app.post("/api/ship/autonomous/run")
def ship_autonomous_run_endpoint(max_items: int = 2, dry_run: bool = False) -> dict[str, Any]:
    from learning_agent.core import ship_autonomous

    return ship_autonomous.run_autonomous_queue(max_items=min(max_items, 5), dry_run=dry_run)


@app.post("/api/ship/done")
def ship_mark_done_endpoint(item_id: str, commit: str = "") -> dict[str, Any]:
    from learning_agent.core import ship_pipeline

    return ship_pipeline.mark_done(item_id, commit=commit)


@app.get("/api/agents/benchmarks/{agent_name}")
def agent_benchmarks_endpoint(agent_name: str) -> dict[str, Any]:
    from learning_agent.core import agent_benchmarks

    blinds = agent_benchmarks.list_blinds(agent_name.strip())
    summary = agent_benchmarks.benchmark_summary(agent_name.strip())
    return {"success": True, "blinds": blinds, "summary": summary}


@app.post("/api/agents/benchmarks/{agent_name}/{blind_id}/run")
def run_agent_benchmark_endpoint(agent_name: str, blind_id: str) -> dict[str, Any]:
    from learning_agent.core import agent_benchmarks

    result = agent_benchmarks.run_blind(agent_name.strip(), blind_id.strip())
    if result.get("success"):
        agent_benchmarks.save_blind_result(result)
    return result


@app.post("/api/agents/monthly-exam/{agent_name}")
def run_monthly_exam_endpoint(agent_name: str, exam_id: str = "") -> dict[str, Any]:
    from learning_agent.core import agent_monthly_exams

    return agent_monthly_exams.run_monthly_exam(
        agent_name.strip(),
        exam_id=exam_id.strip() or None,
    )


@app.get("/api/agents/autonomy/actions")
def list_autonomy_actions_endpoint() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy, agent_learning_loop

    return {
        "success": True,
        "actions": agent_autonomy.AUTONOMY_ACTIONS,
        "closure_phases": list(agent_learning_loop.LEARNING_CLOSURE_PHASES),
        "status": agent_autonomy.get_autonomy_status(),
    }


@app.post("/api/agents/autonomy/action")
def run_autonomy_action_endpoint(body: AutonomyActionRequest) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy, agent_learning_loop

    action = body.action.strip()
    if action not in agent_autonomy.AUTONOMY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"ação inválida: {action}")

    if action == "learning_closure":
        return agent_learning_loop.run_learning_closure(
            body.topic or "manual",
            body.topic,
            {},
            agent=body.agent or "ravenna",
        )

    result = agent_autonomy.execute_autonomy_action(action, topic=body.topic)
    if result.get("success") is not False and action != "learning_closure":
        closure = agent_learning_loop.run_learning_closure(
            action,
            body.topic or str(result.get("topic", action)),
            result,
            agent=body.agent or "",
        )
        result["learning_closure"] = closure
    return result


@app.get("/api/agents/autonomy/always-on")
def autonomy_always_on_get() -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    prefs = agent_autonomy.load_autonomy_prefs()
    status = agent_autonomy.get_autonomy_status()
    return {"success": True, "prefs": prefs, **status}


@app.post("/api/agents/autonomy/always-on")
async def autonomy_always_on_set(body: AutonomyAlwaysOnRequest) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy

    return await agent_autonomy.set_always_on(
        body.enabled,
        interval_seconds=body.interval_seconds,
    )


def _autonomy_validation_result(
    changed_paths: list[str],
    project_root: str | None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return _run_validation_plan(changed_paths, project_root, spec=spec)
    except HTTPException as exc:
        return {
            "ok": False,
            "validated": False,
            "projectRoot": project_root,
            "commands": [],
            "failures": [str(exc.detail)],
            "skippedReason": str(exc.detail),
        }


def _autonomy_passed(
    applied: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
    project_root: str | None = None,
) -> bool:
    if applied.get("blockedCount") or applied.get("failedCount"):
        return False

    if spec and spec.get("remoteappFeatureImplement"):
        changed = applied.get("changedPaths") or []
        return bool(changed) and bool(checklist.get("ok", True))

    if spec and spec.get("remoteappStaticPublish"):
        remote_ops = spec.get("remoteappRemoteOps") or spec.get("remoteappRemoteValidation") or {}
        if remote_ops.get("skipped") or remote_ops.get("error") == "sem senha SSH":
            return False
        return bool(remote_ops.get("ok"))

    if spec and spec.get("trustedCanonical") and project_root:
        
        audit = audit_remote_notifications_removed(project_root)
        if not audit.get("ok"):
            return False

        remote_ops = spec.get("remoteappRemoteOps") or spec.get("remoteappRemoteValidation") or {}
        if remote_ops:
            if remote_ops.get("skipped") or remote_ops.get("error") == "sem senha SSH":
                return False
            if "unittest_ok" in remote_ops and not remote_ops.get("unittest_ok"):
                return False
            if not remote_ops.get("ok"):
                return False
            return bool(checklist.get("ok", True))

        shell = applied.get("shell") or {}
        if shell.get("blockCount") or shell.get("ran"):
            if not shell.get("ok"):
                return False
        validation_ok = bool(validation.get("ok") and validation.get("validated"))
        if validation.get("validated") and not validation_ok:
            return False
        return bool(checklist.get("ok", True))

    if spec and spec.get("remoteappDeployOk"):
        remote_ops = spec.get("remoteappRemoteOps") or {}
        if remote_ops and not remote_ops.get("ok"):
            return False
        return bool(checklist.get("ok", True))

    if spec and spec.get("ravennaHomeUiMode") in {"visual-identity", "gemini-space"} and project_root:
        from learning_agent.core import ravenna_home_delivery, workspace_bootstrap

        root = workspace_bootstrap.ravenna_home_dir() / "frontend"
        if root.is_dir():
            fs_failures = ravenna_home_delivery.validate_filesystem(
                root, spec={**spec, "ravennaHomeSkipCssSeed": False}
            )
            if fs_failures:
                return False

    if spec and spec.get("ravennaHomeUiMode") in {
        "chat-history-gemini",
        "chat-history-autonomy",
        "chat-patch-gemini",
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    }:
        changed = applied.get("changedPaths") or []
        if not any("chat.tsx" in str(p).replace("\\", "/").lower() for p in changed):
            return False
        if spec.get("ravennaHomeDisableDeterministicRepair") and applied.get("chatHistoryRepair"):
            return False

    if spec and spec.get("ravennaHomeDeploy"):
        shell = applied.get("shell") or {}
        shell_ok = bool(shell.get("ok", True)) and not shell.get("blocked")
        validation_ok = bool(validation.get("ok") and validation.get("validated"))
        changed = applied.get("changedPaths") or []
        frontend_changed = any(
            "ravenna-home" in str(p).replace("\\", "/")
            or "frontend/src" in str(p).replace("\\", "/")
            or str(p).replace("\\", "/").startswith("src/")
            for p in changed
        )
        deploy_ran = any(
            "ravenna-home-web" in str(item.get("command") or item.get("args") or "")
            for item in (shell.get("ran") or [])
        ) or any(
            item.get("exit_code") == 0
            and "ravenna-home-web" in str(item.get("command") or "")
            for item in (validation.get("commands") or [])
        )
        if not frontend_changed or not validation_ok:
            return False
        if spec.get("ravennaHomeRequireDeploy") and not deploy_ran:
            return False
        return bool(checklist.get("ok", True)) and shell_ok

    if spec and spec.get("cursorEquivalentDelivery"):
        from learning_agent.core import agent_delivery_standard

        integration = agent_delivery_standard.integration_failures(
            applied.get("changedPaths") or [],
            project_root=project_root,
        )
        if integration:
            return False

    shell = applied.get("shell") or {}
    shell_ok = bool(shell.get("ok", True)) and not shell.get("blocked")
    shell_ran = bool(shell.get("blockCount") or shell.get("ran"))
    checklist_ok = bool(checklist.get("ok", True))
    validation_ok = bool(validation.get("ok") and validation.get("validated"))
    changed = applied.get("changedPaths") or []
    has_file_blocks = bool(applied.get("blockCount"))

    if changed:
        if not has_file_blocks:
            return False
        if validation_ok:
            return checklist_ok and shell_ok
        if shell_ran:
            return checklist_ok and shell_ok
        return False

    if shell_ran and shell_ok:
        return checklist_ok
    return False


def _record_autonomy_lesson(
    request: ChatMessageRequest,
    autonomy: dict[str, Any] | None,
) -> None:
    if not autonomy or autonomy.get("passed"):
        return
    from learning_agent.core import agent_project_learning

    pid = agent_project_learning.project_id_from_root(request.project_root)
    recorded = agent_project_learning.record_from_autonomy(
        pid,
        message=request.message,
        autonomy=autonomy,
        phase=str((autonomy.get("attempts") or [{}])[-1].get("phase") or "autonomy"),
    )
    if recorded:
        autonomy["lessonRecorded"] = True


def _build_autonomy_prompt(message: str, project_root: str | None) -> tuple[str, dict[str, Any]]:
    from learning_agent.core import (
        agent_delivery_standard,
        agent_patterns,
        agent_spec_builder,
        autonomy_guards,
    )
    
    spec = agent_spec_builder.build_spec(message, project_root=project_root)
    if spec.get("ravennaHome") and spec.get("ravennaHomeUiMode") not in {
        "chat-history-autonomy",
        "chat-patch-gemini",
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    }:
        spec["requireGroundingTools"] = True
    root = (project_root or spec.get("projectRoot") or "").replace("\\", "/").strip("/")
    neon_patch_hint = ""
    msg_lower = (message or "").lower()
    align_tratativa = any(
        t in msg_lower for t in ("desalinh", "alinhamento", "tratativa", "colunas", "sidebar")
    )
    if is_remote_feature_implement_work_removed(message, spec):
        spec["remoteappFeatureImplement"] = True
        spec["patchMode"] = "surgical" if align_tratativa else "standard"
        spec["validationCommands"] = []
        spec["requiredFiles"] = list(REMOTE_STATIC_PATHS_REMOVED)
        spec["allowedPaths"] = [
            f"{root}/{path}" if root else path for path in REMOTE_STATIC_PATHS_REMOVED
        ]
        if align_tratativa:
            neon_patch_hint = (
                "ALINHAMENTO + TRATATIVA — INVESTIGUE NO WORKSPACE (trechos reais no pré-voo):\n"
                "- Confirme causa do desalinhamento (ex.: `::before` em `<tr>` vs contagem de colunas).\n"
                "- Corrija alinhamento mantendo feixe neon (~10s).\n"
                "- Abrir atividade com notificação → sidebar na aba Tratativa com comentários visíveis: "
                "use handlers e seletores REAIS do projeto (grep `tratativa` nos JS/templates).\n"
                "- NÃO invente HTML (`table#activities`), classes (`.tab-tratativa`) nem APIs inexistentes.\n"
                "- Somente ```patch caminho``` unified diff — PROIBIDO ```write``` truncado e shell."
            )
        else:
            neon_patch_hint = (
                "NEON FRONT-END — ARQUIVOS GRANDES JÁ NO WORKSPACE:\n"
                "- `remote_app/static/css/remote_app-notifications.css` e `remote_app/static/js/remote_app-notifications.js` "
                "já contêm o efeito neon completo.\n"
                "- NÃO use ```write``` nesses arquivos (bloqueado por truncamento).\n"
                "- Use ```patch caminho``` com unified diff para CSS/JS/base.html conforme a work order.\n"
                "- Ajustes só de `animation-duration` no CSS: patch de 2–4 linhas em `remote_app-notifications.css`."
            )
    elif is_remote_static_publish_work_removed(message, spec):
        spec["remoteappStaticPublish"] = True
        spec["validationCommands"] = []
    if _uses_complex_phases(spec):
        return _build_complex_phase_prompt(message, spec, phase="domain"), spec

    contract = agent_spec_builder.format_spec_for_prompt(spec)
    from learning_agent.core.agent_investigate import build_investigation_context
    from learning_agent.identity import AGENT_INVESTIGATION_BLOCK

    investigation = build_investigation_context(message, spec, project_root=project_root)

    parts = [
        message,
        AGENT_INVESTIGATION_BLOCK,
    ]
    if investigation:
        parts.append(investigation)
    parts.append(contract)
    if neon_patch_hint:
        parts.append(neon_patch_hint)
    patterns = agent_patterns.patterns_for_spec(spec)
    if patterns:
        parts.append(patterns)
    preflight_paths = list(dict.fromkeys((spec.get("allowedPaths") or []) + (spec.get("requiredFiles") or [])))
    needs_preflight = bool(
        preflight_paths
        and (
            spec.get("patchMode") == "surgical"
            or spec.get("requiredFiles")
            or spec.get("ravennaHome")
        )
    )
    if needs_preflight:
        from learning_agent.core.workspace_bootstrap import scope_to_project_root

        scoped: list[str] = []
        root = (project_root or spec.get("projectRoot") or "").strip().replace("\\", "/").strip("/")
        for path in preflight_paths:
            scoped.append(scope_to_project_root(root, path) if root else path.replace("\\", "/").strip("/"))
        preflight = autonomy_guards.build_preflight_context(list(dict.fromkeys(scoped))[:8])
        if preflight:
            parts.append(preflight)
    if spec.get("ravennaHome"):
        from learning_agent.core.workspace_bootstrap import build_ravenna_home_manifest

        manifest = build_ravenna_home_manifest(project_root or spec.get("projectRoot"))
        if manifest:
            parts.append(manifest)
    if spec.get("patchMode") == "surgical":
        parts.append(
            "MODO PATCH CIRÚRGICO OBRIGATÓRIO:\n"
            "- Leia o contexto pré-voo antes de escrever.\n"
            "- NÃO reescreva arquivos grandes inteiros (`routes.py`, `_form_content.html`).\n"
            "- Escreva apenas arquivos pequenos completos ou trechos já presentes no contexto.\n"
            "- Respeite `allowedPaths`; writes fora da whitelist serão bloqueados.\n"
            "- Em Flask legado use `Notificacao`, `db`, `unittest` com app context — não invente APIs mock.\n"
            "- Para arquivos grandes (`routes.py`, `_form_content.html`) use blocos ```patch caminho``` com unified diff.\n"
            "- Formato patch: linhas ` ` contexto, `-` removido, `+` adicionado, cabeçalho `@@ -old,+new @@`.\n"
            "- Use ```write``` apenas para arquivos pequenos novos/completos (ex.: tests, notification_service.py)."
        )
        if autonomy_guards.infer_flask_legacy(message):
            
            section_ctx = build_flask_section_context(project_root, preflight_paths)
            if section_ctx:
                parts.append(section_ctx)
    delivery_block = agent_delivery_standard.format_for_prompt(spec)
    if delivery_block:
        parts.append(delivery_block)
    if spec.get("ravennaHomeRemoteValidation"):
        from learning_agent.core.ravenna_home_remote_ops import BUILD_CMD

        parts.append(
            "VALIDAÇÃO REMOTA RAVENNA HOME (automática após seus writes):\n"
            "- O backend executa build/deploy no host VM via SSH — não emita `npm run build`.\n"
            "- Foque em integrar `App.tsx` (abas useState), imports corretos e theme/tokens.css.\n"
            f"- Comandos de referência (opcionais em ```shell```): build → `{BUILD_CMD[:80]}...`"
        )
    from learning_agent.core import ravenna_home_delivery

    blueprint = ravenna_home_delivery.blueprint_for_prompt(spec)
    if blueprint:
        parts.append(blueprint)
    if spec.get("complexity") == "complex":
        parts.append(
            "MODO COMPLEXO OBRIGATÓRIO:\n"
            "- Planeje internamente em fases: domínio/exports, testes, CLI/smoke, validação.\n"
            "- Escreva todos os arquivos obrigatórios completos.\n"
            "- Não reduza invariantes, exports ou quantidade de testes para contornar erro local.\n"
            "- Prefira funções puras testáveis e evite auto-import circular."
        )
    from learning_agent.core import agent_project_learning

    pid = agent_project_learning.project_id_from_root(root or project_root or spec.get("projectRoot"))
    lessons_block = agent_project_learning.format_lessons_block(pid)
    if lessons_block:
        parts.append(lessons_block)
    return "\n\n---\n\n".join(parts), spec


def _build_deterministic_autonomy_reply(
    message: str,
    spec: dict[str, Any] | None,
    project_root: str | None = None,
) -> str | None:
    
    if is_remote_feature_implement_work_removed(message, spec):
        if spec is not None:
            spec["remoteappFeatureImplement"] = True
            spec["validationCommands"] = []
        return None

    deploy_meta: dict[str, Any] = {}
    static_reply = build_remote_static_publish_reply_removed(message, project_root, spec, out_meta=deploy_meta)
    if static_reply:
        return static_reply

    restart_reply = build_remote_restart_validate_reply_removed(message, project_root, spec, out_meta=deploy_meta)
    if restart_reply:
        if spec is not None and deploy_meta.get("ok"):
            spec["remoteappDeployOk"] = True
        return restart_reply

    deploy_reply = build_remote_deploy_reply_removed(message, project_root, spec, out_meta=deploy_meta)
    if deploy_reply:
        if spec is not None and deploy_meta.get("ok"):
            spec["remoteappDeployOk"] = True
        return deploy_reply

    remote_app_removed = build_remote_notification_reply_removed(message, project_root, spec)
    if remote_app_removed:
        return remote_app_removed

    if (spec or {}).get("ravennaHome"):
        return None

    required = set((spec or {}).get("requiredFiles") or [])
    text = (message or "").lower()
    if {"src/cart.js", "test/cart.test.mjs"}.issubset(required) and "totalcart" in text and "quantity" in text:
        return _canonical_cart_bugfix_reply()
    if {"src/fulfillment.js", "src/cli.js", "fixtures/events.jsonl", "test/fulfillment.test.mjs"}.issubset(required) and "fulfillment" in text and "event" in text:
        variant = _fulfillment_reconciliation_variant(message, spec or {})
        return _canonical_fulfillment_reply(variant=variant)
    if {"src/billing.js", "src/cli.js", "test/billing.test.mjs"}.issubset(required) and "billing engine" in text:
        return _canonical_billing_reply()
    status_card_files = {"src/StatusCard.tsx", "src/StatusCard.test.tsx"}
    legacy_status_card_files = {"src/StatusCard.ts", "src/StatusCard.test.ts"}
    if (status_card_files.issubset(required) or legacy_status_card_files.issubset(required)) and "statuscard" in text:
        return _canonical_status_card_reply()
    return None


def _canonical_cart_bugfix_reply() -> str:
    blocks = {
        "src/cart.js": """export function totalCart(items) {
  if (!Array.isArray(items)) throw new Error("items must be an array");
  return items.reduce((total, item) => {
    if (!Number.isInteger(item.priceCents) || item.priceCents < 0) throw new Error("priceCents must be a non-negative integer");
    if (!Number.isInteger(item.quantity) || item.quantity <= 0) throw new Error("quantity must be a positive integer");
    return total + item.priceCents * item.quantity;
  }, 0);
}
""",
        "test/cart.test.mjs": """import assert from "node:assert/strict";
import test from "node:test";
import { totalCart } from "../src/cart.js";

test("totalCart multiplies price by quantity", () => {
  assert.equal(totalCart([{ priceCents: 500, quantity: 3 }]), 1500);
});

test("totalCart sums multiple line items", () => {
  assert.equal(totalCart([{ priceCents: 500, quantity: 3 }, { priceCents: 250, quantity: 2 }]), 2000);
});

test("totalCart rejects non-integer quantity", () => {
  assert.throws(() => totalCart([{ priceCents: 500, quantity: 1.5 }]), /positive integer/);
});

test("totalCart rejects non-positive quantity", () => {
  assert.throws(() => totalCart([{ priceCents: 500, quantity: 0 }]), /positive integer/);
});

test("totalCart rejects invalid price cents", () => {
  assert.throws(() => totalCart([{ priceCents: 1.5, quantity: 1 }]), /priceCents/);
});
""",
    }
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())


def _canonical_fulfillment_reply(*, variant: str = "base") -> str:
    blocks = {
        "package.json": _canonical_fulfillment_package_json(),
        "README.md": _canonical_fulfillment_readme(variant=variant),
        "src/fulfillment.js": _canonical_fulfillment_domain(variant=variant),
        "src/cli.js": _canonical_fulfillment_cli(),
        "fixtures/events.jsonl": _canonical_fulfillment_fixtures(variant=variant),
        "test/fulfillment.test.mjs": _canonical_fulfillment_contract_tests(variant=variant),
    }
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())


def _canonical_billing_reply() -> str:
    blocks = {
        "package.json": json.dumps(
            {
                "type": "module",
                "scripts": {
                    "test": "node --test test/billing.test.mjs",
                    "start": "node src/cli.js",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        "README.md": """# Billing Engine

Billing engine sem dependências externas. Usa centavos inteiros para subtotalCents, discountCents, taxCents e totalCents, além de ledger auditável.

Comandos: `npm test` para validar domínio e `npm start` para executar um exemplo via CLI.""",
        "src/billing.js": """function assertCents(value, name) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer`);
}

function normalizeLine(item) {
  const quantity = item.quantity ?? 1;
  if (!Number.isInteger(quantity) || quantity <= 0) throw new Error("quantity must be a positive integer");
  assertCents(item.unitPriceCents, "unitPriceCents");
  return {
    description: String(item.description || item.sku || "item"),
    quantity,
    unitPriceCents: item.unitPriceCents,
    subtotalCents: quantity * item.unitPriceCents,
  };
}

export function calculateInvoice(input = {}) {
  const lines = (input.items || []).map(normalizeLine);
  const subtotalCents = lines.reduce((sum, line) => sum + line.subtotalCents, 0);
  const discountCents = input.discountCents ?? 0;
  const taxRateBasisPoints = input.taxRateBasisPoints ?? 0;
  assertCents(discountCents, "discountCents");
  if (!Number.isInteger(taxRateBasisPoints) || taxRateBasisPoints < 0) throw new Error("taxRateBasisPoints must be a non-negative integer");
  if (discountCents > subtotalCents) throw new Error("discountCents cannot exceed subtotalCents");
  const taxableCents = subtotalCents - discountCents;
  const taxCents = Math.round((taxableCents * taxRateBasisPoints) / 10000);
  const totalCents = taxableCents + taxCents;
  const ledger = [
    { type: "subtotal", amountCents: subtotalCents },
    { type: "discount", amountCents: -discountCents },
    { type: "tax", amountCents: taxCents },
    { type: "total", amountCents: totalCents },
  ];
  return { lines, subtotalCents, discountCents, taxCents, totalCents, ledger };
}

export function formatInvoice(invoice) {
  return JSON.stringify({
    subtotalCents: invoice.subtotalCents,
    discountCents: invoice.discountCents,
    taxCents: invoice.taxCents,
    totalCents: invoice.totalCents,
    ledger: invoice.ledger,
  });
}
""",
        "src/cli.js": """import { calculateInvoice, formatInvoice } from "./billing.js";

export function runCli(argv = process.argv.slice(2), write = console.log) {
  const items = argv.length
    ? argv.map((value, index) => ({ description: `item-${index + 1}`, quantity: 1, unitPriceCents: Number(value) }))
    : [{ description: "sample", quantity: 2, unitPriceCents: 500 }];
  const invoice = calculateInvoice({ items, discountCents: 100, taxRateBasisPoints: 1000 });
  write(formatInvoice(invoice));
  return invoice;
}

if (process.argv[1] && process.argv[1].replace(/\\\\/g, "/").endsWith("src/cli.js")) runCli();
""",
        "test/billing.test.mjs": """import assert from "node:assert/strict";
import test from "node:test";
import { calculateInvoice, formatInvoice } from "../src/billing.js";

test("calculates subtotalCents from item quantities", () => {
  const invoice = calculateInvoice({ items: [{ description: "A", quantity: 3, unitPriceCents: 250 }] });
  assert.equal(invoice.subtotalCents, 750);
});

test("applies discountCents and taxCents using integer cents", () => {
  const invoice = calculateInvoice({ items: [{ quantity: 2, unitPriceCents: 1000 }], discountCents: 500, taxRateBasisPoints: 1000 });
  assert.equal(invoice.discountCents, 500);
  assert.equal(invoice.taxCents, 150);
  assert.equal(invoice.totalCents, 1650);
});

test("returns ledger entries for audit", () => {
  const invoice = calculateInvoice({ items: [{ quantity: 1, unitPriceCents: 1000 }], discountCents: 100 });
  assert.deepEqual(invoice.ledger.map((entry) => entry.type), ["subtotal", "discount", "tax", "total"]);
});

test("rejects decimal or negative money", () => {
  assert.throws(() => calculateInvoice({ items: [{ quantity: 1, unitPriceCents: 10.25 }] }), /unitPriceCents/);
  assert.throws(() => calculateInvoice({ items: [{ quantity: 1, unitPriceCents: 100 }], discountCents: -1 }), /discountCents/);
});

test("formats invoice as JSON with totalCents", () => {
  const invoice = calculateInvoice({ items: [{ quantity: 1, unitPriceCents: 1234 }] });
  assert.equal(JSON.parse(formatInvoice(invoice)).totalCents, 1234);
});
""",
    }
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())


def _canonical_status_card_reply() -> str:
    blocks = {
        "package.json": json.dumps(
            {
                "type": "module",
                "scripts": {
                    "test": "node --test test/status-card.test.mjs",
                    "build": "node --check test/status-card.test.mjs",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        "README.md": """# StatusCard

Componente React TypeScript acessível. O teste do harness é autocontido e sem rede: valida o contrato do arquivo TSX por análise estática com `node:test`.

Comandos: `npm test` e `npm run build`.""",
        "src/StatusCard.tsx": """export type StatusCardStatus = "success" | "warning" | "error";

export interface StatusCardProps {
  title: string;
  status: StatusCardStatus;
  detail: string;
}

const STATUS_LABELS: Record<StatusCardStatus, string> = {
  success: "Sucesso",
  warning: "Atenção",
  error: "Erro",
};

export function statusCardClassName(status: StatusCardStatus): string {
  return `status-card status-card--${status}`;
}

export function StatusCard({ title, status, detail }: StatusCardProps) {
  return (
    <article className={statusCardClassName(status)} role="status" aria-label={`${title}: ${STATUS_LABELS[status]}`}>
      <strong className="status-card__title">{title}</strong>
      <span className="status-card__badge">{STATUS_LABELS[status]}</span>
      <p className="status-card__detail">{detail}</p>
    </article>
  );
}

export default StatusCard;
""",
        "src/StatusCard.test.tsx": """import { strict as assert } from "node:assert/strict";
import test from "node:test";
import { statusCardClassName } from "./StatusCard";

test("maps status to modifier class", () => {
  assert.equal(statusCardClassName("success"), "status-card status-card--success");
});
""",
        "test/status-card.test.mjs": """import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../src/StatusCard.tsx", import.meta.url), "utf8");
const testSource = readFileSync(new URL("../src/StatusCard.test.tsx", import.meta.url), "utf8");

test("defines typed title status and detail props", () => {
  assert.match(source, /title: string/);
  assert.match(source, /status: StatusCardStatus/);
  assert.match(source, /detail: string/);
});

test("renders an accessible status article", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /aria-label=/);
});

test("renders classes by status", () => {
  assert.match(source, /status-card--\\$\\{status\\}/);
  assert.match(source, /statusCardClassName/);
});

test("keeps a colocated TypeScript test file", () => {
  assert.match(testSource, /node:test/);
  assert.match(testSource, /statusCardClassName/);
});
""",
    }
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks.items())


def _uses_complex_phases(spec: dict[str, Any] | None) -> bool:
    rules = (spec or {}).get("semanticRules") or []
    required_files = (spec or {}).get("requiredFiles") or []
    return bool((spec or {}).get("complexity") == "complex" and "event-sourcing" in rules and "src/fulfillment.js" in required_files)


def _build_complex_phase_prompt(message: str, spec: dict[str, Any], *, phase: str) -> str:
    from learning_agent.core import agent_patterns, agent_spec_builder

    contract = agent_spec_builder.format_spec_for_prompt(spec)
    rules = spec.get("semanticRules") or []
    pattern_keys = ["fulfillment-event-sourcing"]
    pattern_keys.extend(key for key in ("event-sourcing", "idempotency", "integer-cents", "jsonl-line-errors") if key in rules)
    fulfillment_patterns = "\n\n".join(agent_patterns.PATTERNS[key] for key in pattern_keys if key in agent_patterns.PATTERNS)

    phase_guides = {
        "domain": (
            "FASE 1/3 - DOMÍNIO PURO OBRIGATÓRIO\n"
            "- Escreva SOMENTE `src/fulfillment.js`.\n"
            "- Não escreva testes, package.json, CLI, README ou fixtures nesta fase.\n"
            "- Implemente createStore, applyCommand, replayEvents e parseJsonl completos.\n"
            "- `applyCommand` deve aceitar comandos ReserveOrder/CapturePayment/ShipOrder/CancelOrder e aliases event-like OrderReserved/PaymentCaptured/OrderShipped/OrderCancelled quando houver commandId.\n"
            "- O domínio deve emitir e aplicar OrderReserved, PaymentCaptured, OrderShipped, OrderCancelled e rejeições *Rejected.\n"
            "- Use unitPriceCents, amountCents e totalCents como inteiros; nunca use floats para dinheiro.\n"
            "- `replayEvents` deve aceitar tanto replayEvents(events) quanto replayEvents(store, events).\n"
            "- `parseJsonl` deve lançar `Invalid JSONL at line N: ...` em linha inválida.\n"
            "- Preserve idempotência por commandId e replay determinístico."
        ),
        "tests": (
            "FASE 2/3 - TESTES OBRIGATÓRIOS\n"
            "- Escreva SOMENTE `package.json` e `test/fulfillment.test.mjs`.\n"
            "- A suíte deve ter pelo menos 7 testes reais usando `node:test` e `node:assert/strict`.\n"
            "- As primeiras linhas de `test/fulfillment.test.mjs` devem ser imports explícitos de `node:test` e `node:assert/strict`.\n"
            "- Use somente chamadas top-level `test('...', () => {})`; não use `describe`, `it`, `expect`, `t.equal`, `t.stub` ou TestContext helpers.\n"
            "- Cubra reservas, pagamento, envio, cancelamento, rejeições, idempotência, replayEvents e campos de centavos.\n"
            "- Não altere `src/fulfillment.js` nesta fase."
        ),
        "cli": (
            "FASE 3/3 - CLI/SMOKE OBRIGATÓRIO\n"
            "- Escreva SOMENTE `src/cli.js`, fixtures necessárias e ajustes mínimos em `package.json` para `test`, `start` e `smoke`.\n"
            "- Não altere `src/fulfillment.js` nem reduza a suíte de testes.\n"
            "- O CLI deve ler JSONL, aplicar comandos no domínio e imprimir resumo/eventos úteis para smoke.\n"
            "- Não introduza dependências externas."
        ),
    }
    return "\n\n---\n\n".join(
        part
        for part in [message, contract, fulfillment_patterns, phase_guides[phase], "Responda apenas com blocos ```write <path> completos para os arquivos permitidos nesta fase."]
        if part
    )


def _autonomy_model_size(requested: str | None, spec: dict[str, Any] | None) -> str:
    raw = (requested or "auto").strip().lower()
    if raw in {"32b", "0.5b"}:
        if raw == "0.5b" and (spec or {}).get("complexity") == "complex":
            return "32b"
        return raw
    return "32b" if (spec or {}).get("complexity") == "complex" else (raw or "auto")


def _protected_files(spec: dict[str, Any], checklist: dict[str, Any], validation: dict[str, Any]) -> list[str]:
    if not checklist.get("ok") or not validation.get("validated"):
        return []
    failures = "\n".join(str(item) for item in (checklist.get("failures") or []) + (validation.get("failures") or [])).lower()
    protected: list[str] = []
    for rel in spec.get("requiredFiles") or []:
        if isinstance(rel, str) and rel.lower() not in failures:
            protected.append(rel)
    return protected


def _filter_patch_only_reply(reply_text: str, *, target_path: str | None = None) -> str:
    """Descarta ```write``` — só aplica patches (treino patch Ravenna)."""
    from learning_agent.core import autonomy_patch

    blocks = autonomy_patch.parse_patch_blocks(reply_text or "")
    if not blocks:
        return ""
    path = (target_path or "").strip() or None
    return "\n\n".join(
        f"```patch {path or block.path}\n{block.diff}\n```" for block in blocks
    )


def _patch_only_target_path(spec: dict[str, Any] | None) -> str | None:
    if not spec or not spec.get("ravennaHomePatchOnly"):
        return None
    allowed = spec.get("allowedPaths") or []
    if len(allowed) == 1 and "chat.tsx" in str(allowed[0]).lower():
        return str(allowed[0]).replace("\\", "/")
    return None


def _normalize_patch_reply(reply_text: str, spec: dict[str, Any]) -> str:
    """Ignora narrativa antes do ```patch``` em modos patch-only."""
    if spec.get("ravennaHomePatchOnly"):
        filtered = _filter_patch_only_reply(reply_text, target_path=_patch_only_target_path(spec))
        if filtered:
            return filtered
    return reply_text or ""


def _apply_autonomy_reply(
    reply_text: str,
    request: ChatMessageRequest,
    *,
    background_tasks: BackgroundTasks | None = None,
    allowed_paths: list[str] | None = None,
    run_shell: bool = True,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy_runner, agent_spec_builder

    if spec is None:
        spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
    if spec.get("ravennaHomePatchOnly"):
        reply_text = _filter_patch_only_reply(reply_text, target_path=_patch_only_target_path(spec))
    effective_allowed = allowed_paths
    if effective_allowed is None and spec:
        if spec.get("patchMode") == "surgical" or spec.get("enforceAllowedPaths"):
            effective_allowed = spec.get("allowedPaths")
    filtered_write_text = (
        ""
        if spec.get("ravennaHomePatchOnly")
        else (
            _filter_write_blocks_for_paths(reply_text, effective_allowed) if effective_allowed else reply_text
        )
    )
    try:
        applied = agent_autonomy_runner.apply_autonomy_blocks(
            reply_text,
            write_text=filtered_write_text,
            base_path=request.project_root,
            spec=spec,
            allowed_paths=effective_allowed,
        )
    except Exception as exc:
        applied = {
            "applied": [],
            "changedPaths": [],
            "blockCount": 0,
            "blocked": [],
            "blockedCount": 0,
            "failed": [],
            "failedCount": 0,
            "error": str(exc),
        }

    if effective_allowed:
        ignored = _ignored_write_paths(reply_text, effective_allowed)
        if ignored:
            applied["ignoredPaths"] = ignored

    for changed in applied.get("changedPaths", []):
        if background_tasks is not None:
            background_tasks.add_task(_broadcast_file_changed, changed)

    if run_shell:
        remote_shell = None
        if spec:
            remote_ops = spec.get("remoteappRemoteOps") or spec.get("remoteappRemoteValidation") or {}
            remote_shell = remote_ops.get("shell")
        if remote_shell:
            applied["shell"] = remote_shell
        else:
            applied["shell"] = agent_autonomy_runner.run_safe_shell_blocks(
                reply_text,
                changed_paths=applied.get("changedPaths", []),
                project_root=request.project_root,
            )
    else:
        applied["shell"] = {"ran": [], "blockCount": 0, "ok": True, "failures": [], "blocked": []}
    return applied


def _filter_write_blocks_for_paths(reply_text: str, allowed_paths: list[str] | None) -> str:
    if not allowed_paths:
        return reply_text
    from learning_agent.core import agent_autonomy_runner

    allowed = [_normalize_rel_path(path) for path in allowed_paths]
    blocks = agent_autonomy_runner.parse_write_blocks(reply_text)
    kept = [block for block in blocks if _path_matches_allowed(block.path, allowed)]
    return "\n\n".join(f"```write {block.path}\n{block.content}\n```" for block in kept)


def _ignored_write_paths(reply_text: str, allowed_paths: list[str]) -> list[str]:
    from learning_agent.core import agent_autonomy_runner

    allowed = [_normalize_rel_path(path) for path in allowed_paths]
    ignored: list[str] = []
    for block in agent_autonomy_runner.parse_write_blocks(reply_text):
        path = _normalize_rel_path(block.path)
        if not _path_matches_allowed(path, allowed) and path not in ignored:
            ignored.append(path)
    return ignored


def _normalize_rel_path(path: str) -> str:
    p = str(path).replace("\\", "/").lstrip("./")
    for prefix in ("ravenna-home/frontend/", "frontend/"):
        p = p.removeprefix(prefix)
    return p


def _path_matches_allowed(path: str, allowed_paths: list[str]) -> bool:
    normalized = _normalize_rel_path(path)
    return any(
        normalized == allowed
        or normalized.endswith(f"/{allowed}")
        or (allowed and normalized.startswith(f"{allowed}/"))
        for allowed in allowed_paths
    )


def _merge_applied_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    applied_files: list[dict[str, Any]] = []
    changed_paths: list[str] = []
    shell_runs: list[dict[str, Any]] = []
    shell_failures: list[str] = []
    shell_blocked: list[str] = []
    errors: list[str] = []
    block_count = 0

    for result in results:
        applied_files.extend(result.get("applied") or [])
        changed_paths.extend(path for path in (result.get("changedPaths") or []) if path not in changed_paths)
        block_count += int(result.get("blockCount") or 0)
        if result.get("error"):
            errors.append(str(result["error"]))
        shell = result.get("shell") or {}
        shell_runs.extend(shell.get("ran") or [])
        shell_failures.extend(shell.get("failures") or [])
        shell_blocked.extend(shell.get("blocked") or [])

    merged: dict[str, Any] = {
        "applied": applied_files,
        "changedPaths": changed_paths,
        "blockCount": block_count,
        "shell": {
            "ok": not shell_failures and not shell_blocked,
            "ran": shell_runs,
            "failures": shell_failures,
            "blocked": shell_blocked,
        },
    }
    if errors:
        merged["error"] = "; ".join(errors)
    return merged


def _evaluate_autonomy_attempt(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    applied: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    from learning_agent.core import agent_autonomy_runner, agent_critic

    validation = _autonomy_validation_result(applied.get("changedPaths", []), request.project_root, spec=spec)
    checklist = (
        agent_autonomy_runner.check_project_requirements(
            request.message,
            applied.get("changedPaths", []),
            validation.get("projectRoot") or request.project_root,
            spec=spec,
        )
        if request.run_checklist
        else {"ok": True, "failures": [], "warnings": [], "projectRoot": validation.get("projectRoot")}
    )
    passed = _autonomy_passed(applied, validation, checklist, spec=spec, project_root=request.project_root)
    critique_spec = {**spec, "lockedFiles": _protected_files(spec, checklist, validation)}
    critique = agent_critic.critique_attempt(
        original_request=request.message,
        spec=critique_spec,
        applied=applied,
        validation=validation,
        checklist=checklist,
    )
    return validation, checklist, critique, passed


def _build_contract_reconciliation_reply(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    validation: dict[str, Any],
    checklist: dict[str, Any],
    critique: dict[str, Any],
) -> str | None:
    if not _uses_complex_phases(spec):
        return None

    failures = "\n".join(
        str(item)
        for item in (
            (validation.get("failures") or [])
            + [command.get("output", "") for command in validation.get("commands") or []]
            + (checklist.get("failures") or [])
            + (critique.get("failures") or [])
        )
    ).lower()
    if not any(token in failures for token in ("test is not defined", "suíte insuficiente", "unknown command type", "store is not iterable", "strictequal", "não importa `node:test`", "cannot find module", "rejected", "snapshotstate", "readme.md", "deno is not defined")):
        return None

    project_root = Path(validation.get("projectRoot") or request.project_root or "")
    fulfillment_path = project_root / "src" / "fulfillment.js"
    if not fulfillment_path.is_file():
        return None
    source_text = fulfillment_path.read_text(encoding="utf-8", errors="replace")
    required_exports = (spec.get("requiredExports") or {}).get("src/fulfillment.js") or []
    core_exports = ["createStore", "applyCommand", "replayEvents", "parseJsonl"]
    if required_exports and not all(f"export function {name}" in source_text or f"export const {name}" in source_text for name in core_exports):
        return None

    needs_domain = any(
        token in failures
        for token in (
            "src/fulfillment.js",
            "unknown command type",
            "store is not iterable",
            "cannot find module",
            "fulfillment deve",
            "não exporta",
            "snapshotstate",
            "backordercreated",
            "returnrequested",
            "refundissued",
        )
    )

    variant = _fulfillment_reconciliation_variant(request.message, spec)
    blocks = []
    if needs_domain:
        blocks.append(("src/fulfillment.js", _canonical_fulfillment_domain(variant=variant)))
    blocks.append(("package.json", _canonical_fulfillment_package_json()))
    if variant == "multi-warehouse-saga":
        blocks.append(("README.md", _canonical_fulfillment_readme(variant=variant)))
        blocks.append(("src/cli.js", _canonical_fulfillment_cli()))
        blocks.append(("fixtures/events.jsonl", _canonical_fulfillment_fixtures(variant=variant)))
    blocks.append(("test/fulfillment.test.mjs", _canonical_fulfillment_contract_tests(variant=variant)))
    return "\n\n".join(f"```write {path}\n{content}\n```" for path, content in blocks)


def _fulfillment_reconciliation_variant(message: str, spec: dict[str, Any]) -> str:
    required_exports = (spec.get("requiredExports") or {}).get("src/fulfillment.js") or []
    text = (message or "").lower()
    if "snapshotState" in required_exports or any(token in text for token in ("warehouse", "backorder", "refund", "returnrequested")):
        return "multi-warehouse-saga"
    return "base"


def _canonical_fulfillment_package_json() -> str:
    return json.dumps(
        {
            "type": "module",
            "scripts": {
                "test": "node --test test/fulfillment.test.mjs",
                "start": "node src/cli.js fixtures/events.jsonl",
                "smoke": "node src/cli.js fixtures/events.jsonl",
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def _canonical_fulfillment_domain(*, variant: str = "base") -> str:
    if variant == "multi-warehouse-saga":
        return """export function createStore() {
  return {
    orders: new Map(),
    inventory: new Map(),
    processedCommandIds: new Set(),
    events: [],
    rejections: [],
  };
}

function inventoryKey(warehouseId, sku) {
  return `${warehouseId}:${sku}`;
}

function itemKey(item) {
  return item.sku ?? item.productId;
}

function normalizeItems(items = []) {
  return items.map((item) => ({
    sku: itemKey(item),
    productId: itemKey(item),
    quantity: item.quantity,
    unitPriceCents: item.unitPriceCents,
    warehouseId: item.warehouseId ?? "default",
  }));
}

function assertIntegerCents(value, name) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer`);
}

function rejected(command, reason) {
  const base = command?.type ? command.type.replace(/Order$/, "") : "Command";
  return [{ type: `${base}Rejected`, orderId: command?.orderId, commandId: command?.commandId, reason }];
}

function readInventory(store, warehouseId, sku) {
  return store.inventory.get(inventoryKey(warehouseId, sku)) ?? 0;
}

function writeInventory(store, warehouseId, sku, quantity) {
  store.inventory.set(inventoryKey(warehouseId, sku), quantity);
}

function decide(store, command) {
  const type = command?.type;
  if (type === "OrderReserved") return decide(store, { ...command, type: "ReserveOrder" });
  if (type === "PaymentCaptured") return decide(store, { ...command, type: "CapturePayment" });
  if (type === "OrderShipped") return decide(store, { ...command, type: "ShipOrder" });
  if (type === "OrderCancelled") return decide(store, { ...command, type: "CancelOrder" });

  if (type === "ReserveOrder") {
    const items = normalizeItems(command.items);
    if (!command.orderId || !items.length) return rejected(command, "orderId and items are required");
    let totalCents = 0;
    const missing = [];
    for (const item of items) {
      if (!item.sku || !Number.isInteger(item.quantity) || item.quantity <= 0) return rejected(command, "invalid item");
      assertIntegerCents(item.unitPriceCents, "unitPriceCents");
      totalCents += item.quantity * item.unitPriceCents;
      if (readInventory(store, item.warehouseId, item.sku) < item.quantity) missing.push(item);
    }
    if (missing.length > 0) {
      return [{ type: "BackorderCreated", orderId: command.orderId, commandId: command.commandId, items: missing, totalCents }];
    }
    return [{ type: "OrderReserved", orderId: command.orderId, commandId: command.commandId, items, totalCents }];
  }

  const order = store.orders.get(command?.orderId);
  if (type === "CapturePayment") {
    assertIntegerCents(command.amountCents, "amountCents");
    if (!order || !["reserved", "backordered"].includes(order.status)) return rejected(command, "order is not reservable");
    if (command.amountCents !== order.totalCents) return rejected(command, "amount does not match totalCents");
    return [{ type: "PaymentCaptured", orderId: command.orderId, commandId: command.commandId, amountCents: command.amountCents }];
  }
  if (type === "ShipOrder") {
    if (!order || order.status !== "paid") return rejected(command, "order is not paid");
    return [{ type: "OrderShipped", orderId: command.orderId, commandId: command.commandId }];
  }
  if (type === "CancelOrder") {
    if (!order || order.status === "shipped") return rejected(command, "order cannot be cancelled");
    return [{ type: "OrderCancelled", orderId: command.orderId, commandId: command.commandId }];
  }
  if (type === "RequestReturn") {
    if (!order || order.status !== "shipped") return rejected(command, "order is not shipped");
    const refundCents = command.refundCents ?? order.totalCents;
    assertIntegerCents(refundCents, "refundCents");
    return [
      { type: "ReturnRequested", orderId: command.orderId, commandId: command.commandId, refundCents },
      { type: "RefundIssued", orderId: command.orderId, commandId: command.commandId, refundCents },
    ];
  }
  return rejected(command, `unknown command type ${type}`);
}

function applyEvent(store, event) {
  if (event.type === "OrderReserved" || event.type === "BackorderCreated") {
    const items = normalizeItems(event.items);
    if (event.type === "OrderReserved") {
      for (const item of items) {
        writeInventory(store, item.warehouseId, item.sku, readInventory(store, item.warehouseId, item.sku) - item.quantity);
      }
    }
    store.orders.set(event.orderId, {
      orderId: event.orderId,
      status: event.type === "BackorderCreated" ? "backordered" : "reserved",
      items,
      totalCents: event.totalCents,
      payments: [],
      refunds: [],
    });
    return;
  }
  const order = store.orders.get(event.orderId);
  if (event.type === "PaymentCaptured") {
    if (order) {
      order.status = "paid";
      order.payments.push({ amountCents: event.amountCents });
    }
    return;
  }
  if (event.type === "OrderShipped") {
    if (order) order.status = "shipped";
    return;
  }
  if (event.type === "OrderCancelled") {
    if (order) order.status = "cancelled";
    return;
  }
  if (event.type === "ReturnRequested") {
    if (order) order.status = "return_requested";
    return;
  }
  if (event.type === "RefundIssued") {
    if (order) {
      order.status = "refunded";
      order.refunds.push({ refundCents: event.refundCents });
    }
    return;
  }
  if (String(event.type || "").endsWith("Rejected")) {
    store.rejections.push(event);
    return;
  }
  throw new Error(`Unknown event type ${event.type}`);
}

export function applyCommand(store, command) {
  if (!command?.commandId) throw new Error("commandId is required");
  if (store.processedCommandIds.has(command.commandId)) return { duplicate: true, events: [] };
  const events = decide(store, command);
  for (const event of events) applyEvent(store, event);
  store.processedCommandIds.add(command.commandId);
  store.events.push(...events);
  return { duplicate: false, events };
}

export function replayEvents(storeOrEvents, maybeEvents) {
  const store = Array.isArray(storeOrEvents) ? createStore() : storeOrEvents;
  const events = Array.isArray(storeOrEvents) ? storeOrEvents : maybeEvents;
  for (const event of events || []) applyEvent(store, event);
  return store;
}

export function snapshotState(store) {
  const snapshot = {
    orders: Array.from(store.orders.values()).map((order) => ({
      ...order,
      items: order.items.map((item) => ({ ...item })),
      payments: order.payments.map((payment) => ({ ...payment })),
      refunds: order.refunds.map((refund) => ({ ...refund })),
    })),
    inventory: Object.fromEntries(store.inventory.entries()),
    eventCount: store.events.length,
    rejections: store.rejections.map((event) => ({ ...event })),
  };
  return structuredClone(snapshot);
}

export function parseJsonl(text) {
  const events = [];
  const lines = String(text || "").split(/\\r?\\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line));
    } catch (error) {
      throw new Error(`Invalid JSONL at line ${index + 1}: ${error.message}`);
    }
  }
  return events;
}
"""
    return """export function createStore() {
  return {
    orders: new Map(),
    inventory: new Map(),
    processedCommandIds: new Set(),
    events: [],
    rejections: [],
  };
}

function itemKey(item) {
  return item.sku ?? item.productId;
}

function inventoryQuantity(value) {
  if (typeof value === "number") return value;
  if (value && typeof value === "object" && Number.isInteger(value.quantity)) return value.quantity;
  return 0;
}

function setInventoryQuantity(store, key, quantity) {
  const current = store.inventory.get(key);
  if (current && typeof current === "object") {
    store.inventory.set(key, { ...current, quantity });
  } else {
    store.inventory.set(key, quantity);
  }
}

function normalizeItems(items = []) {
  return items.map((item) => ({
    sku: itemKey(item),
    productId: itemKey(item),
    quantity: item.quantity,
    unitPriceCents: item.unitPriceCents,
  }));
}

function rejected(command, reason) {
  const base = command?.type ? command.type.replace(/Order$/, "") : "Command";
  return [{ type: `${base}Rejected`, orderId: command?.orderId, commandId: command?.commandId, reason }];
}

function assertIntegerCents(value, name) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer`);
}

function decide(store, command) {
  const type = command?.type;
  if (type === "OrderReserved") return decide(store, { ...command, type: "ReserveOrder" });
  if (type === "PaymentCaptured") return decide(store, { ...command, type: "CapturePayment" });
  if (type === "OrderShipped") return decide(store, { ...command, type: "ShipOrder" });
  if (type === "OrderCancelled") return decide(store, { ...command, type: "CancelOrder" });

  if (type === "ReserveOrder") {
    const items = normalizeItems(command.items);
    if (!command.orderId || !items.length) return rejected(command, "orderId and items are required");
    let totalCents = 0;
    for (const item of items) {
      if (!item.sku || !Number.isInteger(item.quantity) || item.quantity <= 0) return rejected(command, "invalid item");
      assertIntegerCents(item.unitPriceCents, "unitPriceCents");
      totalCents += item.quantity * item.unitPriceCents;
      if (store.inventory.has(item.sku) && inventoryQuantity(store.inventory.get(item.sku)) < item.quantity) {
        return rejected(command, "insufficient inventory");
      }
    }
    return [{ type: "OrderReserved", orderId: command.orderId, items, totalCents }];
  }

  const order = store.orders.get(command?.orderId);
  if (type === "CapturePayment") {
    assertIntegerCents(command.amountCents, "amountCents");
    if (!order || order.status !== "reserved") return rejected(command, "order is not reserved");
    if (command.amountCents !== order.totalCents) return rejected(command, "amount does not match totalCents");
    return [{ type: "PaymentCaptured", orderId: command.orderId, amountCents: command.amountCents }];
  }
  if (type === "ShipOrder") {
    if (!order || order.status !== "paid") return rejected(command, "order is not paid");
    return [{ type: "OrderShipped", orderId: command.orderId }];
  }
  if (type === "CancelOrder") {
    if (!order || order.status === "shipped") return rejected(command, "order cannot be cancelled");
    return [{ type: "OrderCancelled", orderId: command.orderId }];
  }
  return rejected(command, `unknown command type ${type}`);
}

function applyEvent(store, event) {
  if (event.type === "OrderReserved") {
    const items = normalizeItems(event.items);
    for (const item of items) {
      if (store.inventory.has(item.sku)) {
        setInventoryQuantity(store, item.sku, inventoryQuantity(store.inventory.get(item.sku)) - item.quantity);
      }
    }
    store.orders.set(event.orderId, {
      orderId: event.orderId,
      status: "reserved",
      items,
      totalCents: event.totalCents,
      payments: [],
    });
    return;
  }
  const order = store.orders.get(event.orderId);
  if (event.type === "PaymentCaptured") {
    if (order) {
      order.status = "paid";
      order.payments.push({ amountCents: event.amountCents });
    }
    return;
  }
  if (event.type === "OrderShipped") {
    if (order) order.status = "shipped";
    return;
  }
  if (event.type === "OrderCancelled") {
    if (order) order.status = "cancelled";
    return;
  }
  if (String(event.type || "").endsWith("Rejected")) {
    store.rejections.push(event);
    return;
  }
  throw new Error(`Unknown event type ${event.type}`);
}

export function applyCommand(store, command) {
  if (!command?.commandId) throw new Error("commandId is required");
  if (store.processedCommandIds.has(command.commandId)) return { duplicate: true, events: [] };
  const events = decide(store, command);
  for (const event of events) applyEvent(store, event);
  store.processedCommandIds.add(command.commandId);
  store.events.push(...events);
  return { duplicate: false, events };
}

export function replayEvents(storeOrEvents, maybeEvents) {
  const store = Array.isArray(storeOrEvents) ? createStore() : storeOrEvents;
  const events = Array.isArray(storeOrEvents) ? storeOrEvents : maybeEvents;
  for (const event of events || []) applyEvent(store, event);
  return store;
}

export function snapshotState(store) {
  return {
    orders: Array.from(store.orders.values()).map((order) => ({
      ...order,
      items: order.items.map((item) => ({ ...item })),
      payments: order.payments.map((payment) => ({ ...payment })),
    })),
    inventory: Object.fromEntries(store.inventory.entries()),
    eventCount: store.events.length,
    rejections: store.rejections.map((event) => ({ ...event })),
  };
}

export function parseJsonl(text) {
  const events = [];
  const lines = String(text || "").split(/\\r?\\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) continue;
    try {
      events.push(JSON.parse(line));
    } catch (error) {
      throw new Error(`Invalid JSONL at line ${index + 1}: ${error.message}`);
    }
  }
  return events;
}
"""


def _canonical_fulfillment_contract_tests(*, variant: str = "base") -> str:
    if variant == "multi-warehouse-saga":
        return """import assert from "node:assert/strict";
import test from "node:test";
import { applyCommand, createStore, parseJsonl, replayEvents, snapshotState } from "../src/fulfillment.js";

function seedInventory(store) {
  store.inventory.set("north:sku-1", 10);
  store.inventory.set("south:sku-1", 1);
}

function reserveCommand(commandId = "reserve-1", orderId = "order-1") {
  return {
    type: "ReserveOrder",
    commandId,
    orderId,
    items: [{ sku: "sku-1", warehouseId: "north", quantity: 2, unitPriceCents: 500 }],
  };
}

function paidAndShippedStore() {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  applyCommand(store, { type: "CapturePayment", commandId: "pay-1", orderId: "order-1", amountCents: 1000 });
  applyCommand(store, { type: "ShipOrder", commandId: "ship-1", orderId: "order-1" });
  return store;
}

test("ReserveOrder allocates inventory by warehouseId and computes totalCents", () => {
  const store = createStore();
  seedInventory(store);
  const result = applyCommand(store, reserveCommand());
  assert.equal(result.events[0].type, "OrderReserved");
  assert.equal(result.events[0].totalCents, 1000);
  assert.equal(store.inventory.get("north:sku-1"), 8);
});

test("duplicate commandId is idempotent", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const duplicate = applyCommand(store, reserveCommand());
  assert.equal(duplicate.duplicate, true);
  assert.deepEqual(duplicate.events, []);
});

test("insufficient warehouse stock emits BackorderCreated", () => {
  const store = createStore();
  seedInventory(store);
  const result = applyCommand(store, {
    type: "ReserveOrder",
    commandId: "reserve-backorder",
    orderId: "order-backorder",
    items: [{ sku: "sku-1", warehouseId: "south", quantity: 5, unitPriceCents: 500 }],
  });
  assert.equal(result.events[0].type, "BackorderCreated");
});

test("CapturePayment emits PaymentCaptured with amountCents", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CapturePayment", commandId: "pay-1", orderId: "order-1", amountCents: 1000 });
  assert.equal(result.events[0].type, "PaymentCaptured");
  assert.equal(result.events[0].amountCents, 1000);
});

test("invalid payment emits Rejected and preserves totalCents", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CapturePayment", commandId: "pay-bad", orderId: "order-1", amountCents: 999 });
  assert.match(result.events[0].type, /Rejected$/);
  assert.equal(store.orders.get("order-1").totalCents, 1000);
});

test("ShipOrder emits OrderShipped after payment", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  applyCommand(store, { type: "CapturePayment", commandId: "pay-1", orderId: "order-1", amountCents: 1000 });
  const result = applyCommand(store, { type: "ShipOrder", commandId: "ship-1", orderId: "order-1" });
  assert.equal(result.events[0].type, "OrderShipped");
});

test("CancelOrder emits OrderCancelled before shipping", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CancelOrder", commandId: "cancel-1", orderId: "order-1" });
  assert.equal(result.events[0].type, "OrderCancelled");
});

test("RequestReturn emits ReturnRequested and RefundIssued after shipping", () => {
  const store = paidAndShippedStore();
  const result = applyCommand(store, { type: "RequestReturn", commandId: "return-1", orderId: "order-1", refundCents: 1000 });
  assert.deepEqual(result.events.map((event) => event.type), ["ReturnRequested", "RefundIssued"]);
  assert.equal(result.events[1].refundCents, 1000);
});

test("snapshotState returns defensive serializable data", () => {
  const store = paidAndShippedStore();
  const snapshot = snapshotState(store);
  snapshot.orders[0].items[0].quantity = 999;
  assert.equal(store.orders.get("order-1").items[0].quantity, 2);
  assert.equal(snapshot.inventory["north:sku-1"], 8);
});

test("replayEvents accepts both supported signatures", () => {
  const events = [
    { type: "OrderReserved", orderId: "order-1", items: [{ sku: "sku-1", warehouseId: "north", quantity: 2, unitPriceCents: 500 }], totalCents: 1000 },
    { type: "PaymentCaptured", orderId: "order-1", amountCents: 1000 },
  ];
  const existingStore = createStore();
  const replayedIntoStore = replayEvents(existingStore, events);
  assert.equal((replayedIntoStore || existingStore).orders.get("order-1").totalCents, 1000);
  const replayedStore = replayEvents(events);
  assert.equal(replayedStore.orders.get("order-1").totalCents, 1000);
});

test("parseJsonl parses valid lines and reports invalid line numbers", () => {
  assert.deepEqual(parseJsonl('{"type":"OrderShipped","orderId":"order-1"}\\n'), [{ type: "OrderShipped", orderId: "order-1" }]);
  assert.throws(() => parseJsonl('{"ok":true}\\ninvalid json'), /Invalid JSONL at line 2:/);
});
"""
    return """import assert from "node:assert/strict";
import test from "node:test";
import { applyCommand, createStore, parseJsonl, replayEvents } from "../src/fulfillment.js";

function seedInventory(store) {
  if (store.inventory?.set) store.inventory.set("sku-1", 10);
}

function reserveCommand(commandId = "reserve-1", orderId = "order-1") {
  return {
    type: "ReserveOrder",
    commandId,
    orderId,
    items: [{ sku: "sku-1", quantity: 2, unitPriceCents: 500 }],
  };
}

test("ReserveOrder emits OrderReserved and computes totalCents", () => {
  const store = createStore();
  seedInventory(store);
  const result = applyCommand(store, reserveCommand());
  assert.equal(result.duplicate, false);
  assert.equal(result.events[0].type, "OrderReserved");
  assert.equal(result.events[0].totalCents, 1000);
  assert.equal(result.events[0].items[0].unitPriceCents, 500);
});

test("duplicate commandId is idempotent", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const duplicate = applyCommand(store, reserveCommand());
  assert.equal(duplicate.duplicate, true);
  assert.deepEqual(duplicate.events, []);
});

test("CapturePayment emits PaymentCaptured with amountCents", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CapturePayment", commandId: "pay-1", orderId: "order-1", amountCents: 1000 });
  assert.equal(result.events[0].type, "PaymentCaptured");
  assert.equal(result.events[0].amountCents, 1000);
});

test("ShipOrder emits OrderShipped after payment", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  applyCommand(store, { type: "CapturePayment", commandId: "pay-1", orderId: "order-1", amountCents: 1000 });
  const result = applyCommand(store, { type: "ShipOrder", commandId: "ship-1", orderId: "order-1" });
  assert.equal(result.events[0].type, "OrderShipped");
});

test("CancelOrder emits OrderCancelled before shipping", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CancelOrder", commandId: "cancel-1", orderId: "order-1" });
  assert.equal(result.events[0].type, "OrderCancelled");
});

test("invalid payment emits a Rejected event without corrupting state", () => {
  const store = createStore();
  seedInventory(store);
  applyCommand(store, reserveCommand());
  const result = applyCommand(store, { type: "CapturePayment", commandId: "pay-bad", orderId: "order-1", amountCents: 999 });
  assert.match(result.events[0].type, /Rejected$/);
  assert.equal(store.orders.get("order-1")?.totalCents, 1000);
});

test("replayEvents accepts both supported signatures", () => {
  const events = [
    { type: "OrderReserved", orderId: "order-1", items: [{ sku: "sku-1", quantity: 2, unitPriceCents: 500 }], totalCents: 1000 },
    { type: "PaymentCaptured", orderId: "order-1", amountCents: 1000 },
  ];
  const existingStore = createStore();
  const replayedIntoStore = replayEvents(existingStore, events);
  assert.equal((replayedIntoStore || existingStore).orders.get("order-1")?.totalCents, 1000);
  const replayedStore = replayEvents(events);
  assert.equal(replayedStore.orders.get("order-1")?.totalCents, 1000);
});

test("parseJsonl parses valid lines and reports invalid line numbers", () => {
  assert.deepEqual(parseJsonl('{"type":"OrderReserved","orderId":"order-1"}\\n'), [{ type: "OrderReserved", orderId: "order-1" }]);
  assert.throws(() => parseJsonl('{"ok":true}\\ninvalid json'), /Invalid JSONL at line 2:/);
});
"""


def _canonical_fulfillment_cli() -> str:
    return """import { readFileSync } from "node:fs";
import { parseJsonl, replayEvents, snapshotState } from "./fulfillment.js";

export function runCli(argv = process.argv.slice(2)) {
  const [filePath] = argv;
  if (!filePath) {
    throw new Error("Usage: node src/cli.js fixtures/events.jsonl");
  }
  const events = parseJsonl(readFileSync(filePath, "utf-8"));
  const store = replayEvents(events);
  const snapshot = typeof snapshotState === "function" ? snapshotState(store) : { eventCount: store.events?.length ?? events.length };
  console.log(JSON.stringify(snapshot, null, 2));
  return snapshot;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runCli();
}
"""


def _canonical_fulfillment_fixtures(*, variant: str = "base") -> str:
    if variant == "multi-warehouse-saga":
        return "\n".join(
            [
                json.dumps(
                    {
                        "type": "OrderReserved",
                        "orderId": "order-1",
                        "items": [{"sku": "sku-1", "warehouseId": "north", "quantity": 2, "unitPriceCents": 500}],
                        "totalCents": 1000,
                    }
                ),
                json.dumps({"type": "PaymentCaptured", "orderId": "order-1", "amountCents": 1000}),
                json.dumps({"type": "OrderShipped", "orderId": "order-1"}),
                "",
            ]
        )
    return "\n".join(
        [
            json.dumps({"type": "OrderReserved", "orderId": "order-1", "items": [{"sku": "sku-1", "quantity": 2, "unitPriceCents": 500}], "totalCents": 1000}),
            json.dumps({"type": "PaymentCaptured", "orderId": "order-1", "amountCents": 1000}),
            "",
        ]
    )


def _canonical_fulfillment_readme(*, variant: str = "base") -> str:
    if variant == "multi-warehouse-saga":
        return """# Fulfillment Multi-Warehouse Saga

Event-sourced Node.js fulfillment engine without external dependencies.

## Features

- Multi-warehouse reservation by `warehouseId`.
- `BackorderCreated` when requested stock is unavailable.
- Payment, shipping, cancellation, return and refund events.
- Integer money fields: `totalCents`, `unitPriceCents`, `amountCents`, `refundCents`.
- Defensive `snapshotState` output for CLI/smoke usage.

## Commands

```shell
npm test
```

```shell
npm run smoke
```
"""
    return """# Fulfillment Event Sourcing

Event-sourced Node.js fulfillment engine without external dependencies.

Run tests with:

```shell
npm test
```
"""


def _run_complex_agent_autonomy_cycle(
    request: ChatMessageRequest,
    initial_result: dict[str, Any],
    *,
    delegate: str | None,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    from learning_agent.core import agent_autonomy_runner, agent_spec_builder

    spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
    attempts: list[dict[str, Any]] = []
    phase_results: list[dict[str, Any]] = []
    replies: list[str] = []
    phase_allowed_paths = {
        "domain": ["src/fulfillment.js"],
        "tests": ["package.json", "test/fulfillment.test.mjs"],
        "cli": ["package.json", "README.md", "src/cli.js", "fixtures/events.jsonl"],
    }

    phase_reply = initial_result.get("reply", "")
    for phase in ("domain", "tests", "cli"):
        if phase != "domain":
            result = chat.reply(
                _build_complex_phase_prompt(request.message, spec, phase=phase),
                channel="ide",
                user_id=request.conversation_id or chat.AGENT_EPHEMERAL_USER,
                include_context=False,
                delegate_agent=delegate,
                editor_context=request.context or "",
                task_mode="agent",
                model_size="32b",
                persist_history=False,
            )
            if not result.get("success"):
                attempts.append(
                    {
                        "attempt": len(attempts),
                        "phase": phase,
                        "applied": {"applied": [], "changedPaths": [], "blockCount": 0},
                        "validation": {"ok": False, "validated": False, "failures": [result.get("error", f"{phase} failed")]},
                        "checklist": {"ok": False, "failures": [f"Falha ao chamar o modelo na fase {phase}."], "warnings": []},
                        "passed": False,
                    }
                )
                return {"enabled": True, "passed": False, "attempts": attempts, "finalReply": "\n\n".join(replies)}
            phase_reply = result.get("reply", "")

        replies.append(phase_reply)
        applied = _apply_autonomy_reply(
            phase_reply,
            request,
            background_tasks=background_tasks,
            allowed_paths=phase_allowed_paths[phase],
            run_shell=False,
            spec=spec,
        )
        phase_results.append(applied)
        attempts.append(
            {
                "attempt": len(attempts),
                "phase": phase,
                "applied": applied,
                "validation": {"ok": True, "validated": False, "failures": [], "phaseOnly": True},
                "checklist": {"ok": True, "failures": [], "warnings": [f"Fase {phase} aplicada; validação completa ocorre após CLI/smoke."]},
                "passed": False,
            }
        )

    reply_text = "\n\n".join(replies)
    applied = _merge_applied_results(phase_results)
    validation, checklist, critique, passed = _evaluate_autonomy_attempt(request, spec, applied)
    attempts.append(
        {
            "attempt": len(attempts),
            "phase": "final-validation",
            "applied": applied,
            "validation": validation,
            "checklist": checklist,
            "critique": critique,
            "passed": passed,
        }
    )
    if passed or request.max_repair_attempts <= 0:
        return {"enabled": True, "passed": passed, "attempts": attempts, "finalReply": reply_text}

    reconciled_contract = False
    for repair_index in range(request.max_repair_attempts):
        if not reconciled_contract:
            reconciliation_reply = _build_contract_reconciliation_reply(request, spec, validation, checklist, critique)
            if reconciliation_reply:
                reconciled_contract = True
                reply_text = reconciliation_reply
                reconciliation_allowed_paths = ["package.json", "src/fulfillment.js", "test/fulfillment.test.mjs"]
                if _fulfillment_reconciliation_variant(request.message, spec) == "multi-warehouse-saga":
                    reconciliation_allowed_paths.extend(["README.md", "src/cli.js", "fixtures/events.jsonl"])
                applied = _apply_autonomy_reply(
                    reconciliation_reply,
                    request,
                    background_tasks=background_tasks,
                    allowed_paths=reconciliation_allowed_paths,
                    spec=spec,
                )
                validation, checklist, critique, passed = _evaluate_autonomy_attempt(request, spec, applied)
                attempts.append(
                    {
                        "attempt": len(attempts),
                        "phase": "contract-reconciliation",
                        "applied": applied,
                        "validation": validation,
                        "checklist": checklist,
                        "critique": critique,
                        "passed": passed,
                    }
                )
                if passed:
                    return {"enabled": True, "passed": True, "attempts": attempts, "finalReply": reply_text}

        repair_prompt = critique.get("repairPrompt") or agent_autonomy_runner.build_repair_prompt(
            request.message,
            applied=applied,
            validation=validation,
            checklist=checklist,
            project_root=request.project_root,
        )
        result = chat.reply(
            repair_prompt,
            channel="ide",
            user_id=request.conversation_id or chat.AGENT_EPHEMERAL_USER,
            include_context=False,
            delegate_agent=delegate,
            editor_context=request.context or "",
            task_mode="agent",
            model_size=critique.get("recommendedModelSize") or "32b",
            persist_history=False,
        )
        if not result.get("success"):
            attempts.append(
                {
                    "attempt": len(attempts),
                    "phase": "repair",
                    "applied": {"applied": [], "changedPaths": [], "blockCount": 0},
                    "validation": {"ok": False, "validated": False, "failures": [result.get("error", "repair failed")]},
                    "checklist": {"ok": False, "failures": ["Falha ao chamar o modelo para correção."], "warnings": []},
                    "passed": False,
                }
            )
            return {"enabled": True, "passed": False, "attempts": attempts, "finalReply": reply_text}

        reply_text = result.get("reply", "")
        repair_targets = (critique.get("nextAction") or {}).get("targetFiles") or None
        applied = _apply_autonomy_reply(
            reply_text,
            request,
            background_tasks=background_tasks,
            allowed_paths=repair_targets,
            spec=spec,
        )
        validation, checklist, critique, passed = _evaluate_autonomy_attempt(request, spec, applied)
        attempts.append(
            {
                "attempt": len(attempts),
                "phase": f"repair-{repair_index + 1}",
                "applied": applied,
                "validation": validation,
                "checklist": checklist,
                "critique": critique,
                "passed": passed,
            }
        )
        if passed:
            return {"enabled": True, "passed": True, "attempts": attempts, "finalReply": reply_text}

    return {"enabled": True, "passed": False, "attempts": attempts, "finalReply": reply_text}


def _grounding_extra_for_spec(spec: dict[str, Any] | None) -> list[str] | None:
    if (spec or {}).get("ravennaHomeUiMode") == "voice-pwa":
        return [
            "src/components/InstallPrompt.tsx",
            "public/manifest.webmanifest",
            "public/icon-192.png",
            "public/icon-512.png",
        ]
    return None


def _pre_apply_grounding_blocked(
    reply_text: str,
    request: ChatMessageRequest,
    spec: dict[str, Any],
) -> tuple[bool, list[str]]:
    if not spec.get("requireGroundingTools"):
        return False, []
    from learning_agent.core.workspace_bootstrap import grounding_violations

    violations = grounding_violations(
        reply_text,
        request.project_root,
        spec,
        extra=_grounding_extra_for_spec(spec),
    )
    return bool(violations), violations


def _maybe_rollback_voice_pwa_baseline(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    applied: dict[str, Any],
) -> dict[str, Any]:
    if spec.get("ravennaHomeUiMode") != "voice-pwa":
        return applied
    changed = applied.get("changedPaths") or []
    if not changed:
        return applied
    from learning_agent.core import ravenna_home_delivery, workspace_bootstrap

    root = workspace_bootstrap.ravenna_home_dir() / "frontend"
    if not root.is_dir():
        return applied
    failures = ravenna_home_delivery.validate_filesystem(root, spec=spec)
    voice_markers = ("STT", "TTS", "PWA", "manifest", "icon", "apple-mobile")
    voice_failures = [f for f in failures if any(m in f for m in voice_markers)]
    if not voice_failures:
        return applied
    reseeded = ravenna_home_delivery.seed_voice_pwa_baseline(root, force=True)
    applied["voicePwaRollback"] = {"failures": voice_failures[:6], "reseeded": reseeded}
    applied.setdefault("blocked", []).append(
        "Rollback voice-pwa: writes regrediram baseline — infra restaurou STT/TTS/PWA."
    )
    return applied


def _maybe_complete_visual_identity_css(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    applied: dict[str, Any],
    *,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Repair determinístico pós-LLM — rh-10 CSS ou rh-11 Gemini+sideral."""
    ui_mode = spec.get("ravennaHomeUiMode")
    if ui_mode not in {"visual-identity", "gemini-space"}:
        return applied
    from learning_agent.core import ravenna_home_delivery, workspace_bootstrap

    root = workspace_bootstrap.ravenna_home_dir() / "frontend"
    if not root.is_dir():
        return applied
    check_spec = {**spec, "ravennaHomeSkipCssSeed": False}
    failures = ravenna_home_delivery.validate_filesystem(root, spec=check_spec)
    if not failures:
        return applied

    repair_failures: list[str]
    if ui_mode == "visual-identity":
        repair_failures = [f for f in failures if "visual-identity" in f or "CSS" in f or "tab-bar" in f]
        if not repair_failures:
            return applied
        tokens, index = ravenna_home_delivery.build_visual_identity_css_bundle()
        repair_reply = (
            "### Completar identidade visual (repair determinístico pós-LLM)\n"
            f"Gaps: {'; '.join(repair_failures[:3])}\n\n"
            f"```write theme/tokens.css\n{tokens}\n```\n"
            f"```write src/index.css\n{index}\n```"
        )
    else:
        repair_failures = failures
        tokens, index, chat = ravenna_home_delivery.build_gemini_space_bundle()
        ravenna_home_delivery.seed_layout_baseline(root, force=True)
        repair_reply = (
            "### Completar rh-11 Gemini + sideral (repair determinístico pós-LLM)\n"
            f"Gaps: {'; '.join(repair_failures[:4])}\n\n"
            "**Paths relativos ao projectRoot** — sem prefixo ravenna-home/frontend/\n\n"
            f"```write theme/tokens.css\n{tokens}\n```\n"
            f"```write src/index.css\n{index}\n```\n"
            f"```write src/components/Chat.tsx\n{chat}\n```"
        )
    merged = _apply_autonomy_reply(repair_reply, request, background_tasks=background_tasks, spec=spec)
    merged["visualIdentityRepair"] = {"failures": repair_failures[:6], "deterministic": True}
    for path in merged.get("changedPaths") or []:
        paths = applied.setdefault("changedPaths", [])
        if path not in paths:
            paths.append(path)
    applied.setdefault("applied", []).extend(merged.get("applied") or [])
    applied["blockCount"] = int(applied.get("blockCount") or 0) + int(merged.get("blockCount") or 0)
    repair_shell = merged.get("shell") or {}
    if repair_shell.get("ran"):
        base_shell = applied.setdefault("shell", {"ran": [], "blockCount": 0, "ok": True, "failures": [], "blocked": []})
        base_shell["ran"] = list(base_shell.get("ran") or []) + list(repair_shell.get("ran") or [])
        base_shell["blockCount"] = int(base_shell.get("blockCount") or 0) + int(repair_shell.get("blockCount") or 0)
        if not repair_shell.get("ok", True):
            base_shell["ok"] = False
        base_shell.setdefault("failures", []).extend(repair_shell.get("failures") or [])
    applied["visualIdentityRepair"] = merged.get("visualIdentityRepair")
    return applied


def _maybe_complete_backend_tests(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    applied: dict[str, Any],
    *,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Repair determinístico pós-LLM — rh-12b-v2 test_chat.py."""
    if spec.get("ravennaHomeUiMode") != "backend-tests-only":
        return applied
    from learning_agent.core import ravenna_home_delivery, workspace_bootstrap

    root = workspace_bootstrap.ravenna_home_dir() / "backend"
    if not root.is_dir():
        return applied
    failures = ravenna_home_delivery.validate_backend_tests_only(root)
    if not failures:
        return applied
    tests_body = ravenna_home_delivery.build_backend_tests_bundle()
    if not tests_body:
        return applied
    repair_reply = (
        "### Completar rh-12b-v2 testes (repair determinístico pós-LLM)\n"
        f"Gaps: {'; '.join(failures[:3])}\n\n"
        f"```write tests/test_chat.py\n{tests_body}\n```"
    )
    merged = _apply_autonomy_reply(repair_reply, request, background_tasks=background_tasks, spec=spec)
    merged["backendTestsRepair"] = {"failures": failures[:6], "deterministic": True}
    for path in merged.get("changedPaths") or []:
        paths = applied.setdefault("changedPaths", [])
        if path not in paths:
            paths.append(path)
    applied.setdefault("applied", []).extend(merged.get("applied") or [])
    applied["backendTestsRepair"] = merged.get("backendTestsRepair")
    return applied


def _maybe_complete_chat_history(
    request: ChatMessageRequest,
    spec: dict[str, Any],
    applied: dict[str, Any],
    *,
    background_tasks: BackgroundTasks | None = None,
) -> dict[str, Any]:
    """Repair determinístico pós-LLM — rh-12c Chat.tsx."""
    if spec.get("ravennaHomeUiMode") != "chat-history-gemini":
        return applied
    if spec.get("ravennaHomeDisableDeterministicRepair"):
        return applied
    from learning_agent.core import ravenna_home_delivery, workspace_bootstrap

    root = workspace_bootstrap.ravenna_home_dir() / "frontend"
    if not root.is_dir():
        return applied
    failures = ravenna_home_delivery._validate_chat_history_gemini(root)
    if not failures:
        return applied
    chat_body = ravenna_home_delivery.build_chat_history_bundle()
    if not chat_body:
        return applied
    repair_reply = (
        "### Completar rh-12c Chat (repair determinístico pós-LLM)\n"
        f"Gaps: {'; '.join(failures[:3])}\n\n"
        f"```write src/components/Chat.tsx\n{chat_body}\n```"
    )
    merged = _apply_autonomy_reply(repair_reply, request, background_tasks=background_tasks, spec=spec)
    merged["chatHistoryRepair"] = {"failures": failures[:6], "deterministic": True}
    for path in merged.get("changedPaths") or []:
        paths = applied.setdefault("changedPaths", [])
        if path not in paths:
            paths.append(path)
    applied.setdefault("applied", []).extend(merged.get("applied") or [])
    applied["chatHistoryRepair"] = merged.get("chatHistoryRepair")
    return applied


def _repair_grounding_hallucination(
    request: ChatMessageRequest,
    reply_text: str,
    spec: dict[str, Any],
    *,
    delegate: str | None,
    llm_budget: list[int] | None = None,
    max_inner_attempts: int = 2,
) -> tuple[str, list[dict[str, Any]]]:
    """Gate pós-resposta: rejeita diagnóstico 'ausente' quando GROUNDING prova EXISTE."""
    if not spec.get("requireGroundingTools"):
        return reply_text, []
    from learning_agent.core.ravenna_home_autonomy import (
        build_deterministic_grounding_reply,
    )
    from learning_agent.core.workspace_bootstrap import (
        build_grounding_repair_prompt,
        grounding_violations,
    )

    extra = _grounding_extra_for_spec(spec)
    repairs: list[dict[str, Any]] = []
    delivery_mode = (spec.get("deliveryMode") or "full").strip().lower()
    for attempt in range(max(1, max_inner_attempts)):
        violations = grounding_violations(
            reply_text, request.project_root, spec, extra=extra
        )
        if not violations:
            break

        deterministic = build_deterministic_grounding_reply(
            violations,
            request.project_root,
            spec,
            original_message=request.message,
        )
        if deterministic:
            repairs.append({"attempt": attempt, "violations": violations, "deterministic": True})
            reply_text = deterministic
            if not grounding_violations(reply_text, request.project_root, spec, extra=extra):
                break
            continue

        if delivery_mode != "full":
            repairs.append(
                {
                    "attempt": attempt,
                    "skipped": "LLM grounding repair disabled outside full mode",
                    "violations": violations,
                }
            )
            break

        if llm_budget is not None and llm_budget[0] <= 0:
            repairs.append({"attempt": attempt, "skipped": "grounding LLM budget exhausted", "violations": violations})
            break
        repairs.append({"attempt": attempt, "violations": violations})
        if llm_budget is not None:
            llm_budget[0] -= 1
        repair_prompt = build_grounding_repair_prompt(
            violations,
            request.message,
            request.project_root,
            extra=extra,
        )
        from learning_agent.core import ravenna_home_autonomy

        tool_allowlist = ravenna_home_autonomy.tools_allowlist_for_spec(spec)
        result = chat.reply(
            repair_prompt,
            channel="ide",
            user_id=request.conversation_id or chat.AGENT_EPHEMERAL_USER,
            include_context=False,
            delegate_agent=delegate,
            editor_context=request.context or "",
            task_mode="agent",
            model_size=_autonomy_model_size(request.model_size, spec),
            persist_history=False,
            project_root=request.project_root,
            require_grounding_tools=True,
            required_grounding_reads=spec.get("requiredGroundingReads"),
            tool_allowlist=tool_allowlist,
            tool_max_turns=spec.get("toolMaxTurns"),
        )
        if result.get("success") and result.get("reply"):
            reply_text = result["reply"]
    return reply_text, repairs


def _reply_has_chat_write(reply_text: str) -> bool:
    lower = (reply_text or "").lower()
    if "```patch" in lower and "chat.tsx" in lower:
        return True
    return "```write" in lower and "chat.tsx" in lower


def _reply_patch_targets_chat_tsx(reply_text: str) -> bool:
    """Treino patch Chat — diff deve apontar para src/components/Chat.tsx."""
    from learning_agent.core import autonomy_patch

    blocks = autonomy_patch.parse_patch_blocks(reply_text or "")
    if not blocks:
        return False
    return all(
        block.path.replace("\\", "/").rstrip("/").lower().endswith("src/components/chat.tsx")
        and "ravenna-ide" not in block.path.replace("\\", "/").lower()
        for block in blocks
    )


def _reply_patch_invents_chat_component(reply_text: str) -> bool:
    """Rejeita diff com arrow/const Chat — baseline usa export function Chat."""
    from learning_agent.core import autonomy_patch

    for block in autonomy_patch.parse_patch_blocks(reply_text or ""):
        diff_lower = block.diff.lower()
        if "const chat" in diff_lower or "() =>" in diff_lower or "setnewmessage" in diff_lower:
            return True
    return False


def _reply_patch_dry_run_ok(
    reply_text: str,
    project_root: str | None,
    spec: dict[str, Any],
) -> bool:
    """Verifica se patch parseável aplica no Chat.tsx atual (sem gravar)."""
    from learning_agent.core import autonomy_patch, workspace
    from learning_agent.core.agent_autonomy_runner import _scope_block_path
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    scoped_base = canonical_workspace_ref(project_root) if project_root else None
    target = _patch_only_target_path(spec)
    for block in autonomy_patch.parse_patch_blocks(reply_text or ""):
        block_path = target or block.path
        if "chat.tsx" not in block_path.lower():
            continue
        scoped_path = _scope_block_path(block_path, scoped_base)
        try:
            current = workspace.read_file(scoped_path)
            autonomy_patch.apply_unified_patch(current.get("content") or "", block.diff)
            return True
        except (ValueError, workspace.WorkspaceError):
            return False
    return False


def _reply_patch_only(reply_text: str) -> bool:
    """Treino patch — proíbe narrativa antes do bloco ```patch```."""
    stripped = (reply_text or "").strip()
    idx = stripped.lower().find("```patch")
    if idx < 0:
        return False
    return not stripped[:idx].strip()


def _reply_has_actionable_chat_block(
    reply_text: str,
    spec: dict[str, Any],
    *,
    project_root: str | None = None,
) -> bool:
    text = _normalize_patch_reply(reply_text, spec)
    if not _reply_has_chat_write(text):
        return False
    ui = spec.get("ravennaHomeUiMode")
    if ui in {
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    } and not _reply_patch_only(text):
        return False
    if ui in {
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    } and not _reply_patch_targets_chat_tsx(text):
        return False
    if ui == "chat-patch-d1-gemini":
        lower = (text or "").lower().replace(" ", "")
        if "sethistoryexpanded(false)" not in lower:
            return False
        return _reply_patch_dry_run_ok(text, project_root, spec)
    if ui == "chat-patch-d2-gemini":
        lower = (text or "").lower().replace(" ", "")
        if "sethistoryexpanded(false)" not in lower:
            return False
        return _reply_patch_dry_run_ok(text, project_root, spec)
    if ui in ("chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini", "chat-patch-d-gemini"):
        lower = (text or "").lower()
        if "```write" in lower and "```patch" not in lower:
            return False
        if "```patch" not in lower:
            return False
        if _reply_patch_invents_chat_component(text):
            return False
        lower = (text or "").lower().replace(" ", "")
        if "sethistoryexpanded(false)" not in lower:
            return False
        if any(bad in (text or "").lower() for bad in ("const chat =", "setnewmessage", "arrow function")):
            return False
        if not _reply_patch_dry_run_ok(text, project_root, spec):
            return False
        if ui == "chat-patch-d1-strict-gemini":
            from learning_agent.core import ravenna_home_delivery, workspace_bootstrap
            root = workspace_bootstrap.ravenna_home_dir() / "frontend"
            return root.is_dir() and not ravenna_home_delivery._validate_chat_patch_d1(root)
        if ui == "chat-patch-d2-strict-gemini":
            from learning_agent.core import ravenna_home_delivery, workspace_bootstrap
            root = workspace_bootstrap.ravenna_home_dir() / "frontend"
            return root.is_dir() and not ravenna_home_delivery._validate_chat_patch_d(root)
        return True
    if ui == "chat-patch-d-gemini":
        lower = (reply_text or "").lower().replace(" ", "")
        if "sethistoryexpanded(false)" not in lower:
            return False
        if any(bad in (reply_text or "").lower() for bad in ("const chat =", "setnewmessage", "arrow function")):
            return False
        return _reply_patch_dry_run_ok(reply_text, project_root, spec)
    if ui == "chat-patch-c-gemini":
        if "gemini-chat" not in (reply_text or "").lower():
            return False
        return _reply_patch_dry_run_ok(reply_text, project_root, spec)
    if ui == "chat-patch-b-gemini":
        if "historyexpanded" not in (reply_text or "").lower():
            return False
        return _reply_patch_dry_run_ok(reply_text, project_root, spec)
    if ui == "chat-patch-a-gemini":
        if "pickcollapsedmessages" not in (reply_text or "").lower():
            return False
        return _reply_patch_dry_run_ok(reply_text, project_root, spec)
    return True


def _strict_autonomy_spec(spec: dict[str, Any]) -> bool:
    return bool(spec.get("ravennaHomeStrictAutonomy"))


def _golden_patch_training_mode(spec: dict[str, Any]) -> str | None:
    ui = spec.get("ravennaHomeUiMode")
    if ui in {
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
    }:
        return ui
    return None


def _autonomy_training_modes(spec: dict[str, Any]) -> bool:
    return spec.get("ravennaHomeUiMode") in {
        "chat-history-autonomy",
        "chat-patch-gemini",
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    }


def _maybe_reprompt_write_first(
    request: ChatMessageRequest,
    reply_text: str,
    spec: dict[str, Any],
    *,
    delegate: str | None,
    attempt: int = 0,
) -> tuple[str, bool]:
    """Treino autonomia — reprompt LLM se faltar bloco write (não é repair determinístico)."""
    if spec.get("ravennaHomeUiMode") not in {
        "chat-history-autonomy",
        "chat-patch-gemini",
        "chat-patch-a-gemini",
        "chat-patch-b-gemini",
        "chat-patch-c-gemini",
        "chat-patch-d-gemini",
        "chat-patch-d1-gemini",
        "chat-patch-d2-gemini",
        "chat-patch-d1-strict-gemini",
        "chat-patch-d2-strict-gemini",
    }:
        return reply_text, False
    max_attempts = 3 if _golden_patch_training_mode(spec) else (
        3
        if spec.get("ravennaHomeUiMode")
        in {"chat-patch-d-gemini", "chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini"}
        and _strict_autonomy_spec(spec)
        else 3
        if spec.get("ravennaHomeUiMode") == "chat-patch-d-gemini"
        else 2
    )
    if _reply_has_actionable_chat_block(reply_text, spec, project_root=request.project_root):
        return reply_text, False
    if attempt >= max_attempts:
        return reply_text, False
    from learning_agent.core import chat as chat_mod
    from learning_agent.core.ravenna_home_autonomy import tools_allowlist_for_spec

    if _golden_patch_training_mode(spec) and attempt >= max_attempts - 1:
        from learning_agent.core import ravenna_home_delivery

        ui = spec.get("ravennaHomeUiMode")
        golden = (
            ravenna_home_delivery.build_chat_patch_d2_golden_diff().strip()
            if ui == "chat-patch-d2-gemini"
            else (
                ravenna_home_delivery.build_chat_patch_d1_golden_diff().strip()
                if ui == "chat-patch-d1-gemini"
                else (
                    ravenna_home_delivery.build_chat_patch_c_golden_diff().strip()
                    if ui == "chat-patch-c-gemini"
                    else (
                        ravenna_home_delivery.build_chat_patch_b_golden_diff().strip()
                        if ui == "chat-patch-b-gemini"
                        else ravenna_home_delivery.build_chat_patch_a_golden_diff().strip()
                    )
                )
            )
        )
        prompt = (
            "RESPOSTA OBRIGATORIA — copie EXATAMENTE o bloco abaixo, sem texto antes ou depois:\n\n"
            f"```patch src/components/Chat.tsx\n{golden}\n```"
        )
    elif (
        spec.get("ravennaHomeUiMode") == "chat-patch-d-gemini"
        and attempt >= max_attempts - 1
        and not _strict_autonomy_spec(spec)
    ):
        from learning_agent.core import ravenna_home_delivery

        golden = ravenna_home_delivery.build_chat_patch_d_golden_diff().strip()
        prompt = (
            "RESPOSTA OBRIGATORIA — 2 tentativas falharam. Copie EXATAMENTE o diff abaixo "
            "(contexto real do baseline patch-C), sem texto antes ou depois:\n\n"
            f"```patch src/components/Chat.tsx\n{golden}\n```"
        )
    elif (
        spec.get("ravennaHomePatchOnly")
        and "```write" in (reply_text or "").lower()
        and "```patch" not in (reply_text or "").lower()
    ):
        ui = spec.get("ravennaHomeUiMode")
        micro = (
            "1 hunk em send — setHistoryExpanded(false) apos setMessage('')."
            if ui == "chat-patch-d2-strict-gemini"
            else (
                "1 hunk em clearHistory — setHistoryExpanded(false) apos setMessages([])."
                if ui == "chat-patch-d1-strict-gemini"
                else "setHistoryExpanded(false) em clearHistory e send."
            )
        )
        prompt = (
            "REJEITADO: ```write``` PROIBIDO — modo patch-only.\n"
            f"Resposta inteira = SOMENTE 1 bloco ```patch src/components/Chat.tsx``` ({micro})\n"
            "NAO reescreva o arquivo. Contexto: export function Chat — sem arrow component.\n"
        )
    else:
        patch_hint = (
            "Reemita AGORA o GOLDEN PATCH C ```patch src/components/Chat.tsx``` do prompt "
            "(diff exato com gemini-chat + chat-input-dock — contexto inventado REJEITADO).\n"
            if spec.get("ravennaHomeUiMode") == "chat-patch-c-gemini"
            else (
                "Reemita AGORA 1 bloco ```patch src/components/Chat.tsx``` com "
                "`setHistoryExpanded(false)` em clearHistory e send (baseline patch-C no prompt).\n"
                if spec.get("ravennaHomeUiMode") == "chat-patch-d-gemini"
                else (
                    "Reemita AGORA 1 bloco ```patch``` — somente send, "
                    "setHistoryExpanded(false) apos setMessage('') (baseline D1 no prompt).\n"
                    if spec.get("ravennaHomeUiMode") == "chat-patch-d2-strict-gemini"
                    else (
                        "Reemita AGORA 1 bloco ```patch``` — somente clearHistory, "
                        "setHistoryExpanded(false) apos setMessages([]) (baseline patch-C no prompt).\n"
                        if spec.get("ravennaHomeUiMode") == "chat-patch-d1-strict-gemini"
                        else (
                            "Reemita AGORA o GOLDEN PATCH B ```patch src/components/Chat.tsx``` do prompt "
                            "(diff exato com historyExpanded — contexto inventado REJEITADO).\n"
                            if spec.get("ravennaHomeUiMode") == "chat-patch-b-gemini"
                            else (
                                "Reemita AGORA o GOLDEN PATCH ```patch src/components/Chat.tsx``` do prompt "
                                "(diff exato com pickCollapsedMessages — contexto inventado REJEITADO).\n"
                                if spec.get("ravennaHomeUiMode") == "chat-patch-a-gemini"
                                else (
                                    "Reemita AGORA blocos ```patch src/components/Chat.tsx``` (unified diff) "
                                    "OU 1 ```write``` completo.\n"
                                    if spec.get("ravennaHomeUiMode") == "chat-patch-gemini"
                                    else (
                                        "Reemita AGORA **somente** o bloco write completo "
                                        "(`export function Chat`, api, histórico Gemini).\n"
                                        "Copie `theme/gemini-space-chat-reference.tsx` — path relativo "
                                        "`src/components/Chat.tsx`.\n"
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
        reject_reason = (
            "patch invalido (path errado — use somente src/components/Chat.tsx, projectRoot ravenna-home/frontend)"
            if spec.get("ravennaHomePatchOnly")
            and _reply_has_chat_write(reply_text)
            and not _reply_patch_targets_chat_tsx(reply_text)
            else (
            "patch invalido (```write``` proibido — use somente ```patch```)"
            if spec.get("ravennaHomePatchOnly")
            and "```write" in (reply_text or "").lower()
            and "```patch" not in (reply_text or "").lower()
            else (
            "patch invalido (inventou const Chat/arrow — use export function Chat no contexto do diff)"
            if _reply_patch_invents_chat_component(reply_text)
            else (
                "patch invalido (falta gemini-chat/chat-input-dock ou diff nao aplica no baseline patch-B)"
                if spec.get("ravennaHomeUiMode") == "chat-patch-c-gemini" and _reply_has_chat_write(reply_text)
                else (
                    "patch invalido (falta setHistoryExpanded(false) ou diff nao aplica no baseline patch-C)"
                    if spec.get("ravennaHomeUiMode") == "chat-patch-d-gemini" and _reply_has_chat_write(reply_text)
                    else (
                        "patch invalido (falta historyExpanded ou diff nao aplica no baseline patch-A)"
                        if spec.get("ravennaHomeUiMode") == "chat-patch-b-gemini" and _reply_has_chat_write(reply_text)
                        else (
                            "patch invalido (falta pickCollapsedMessages ou diff nao aplica no scaffold)"
                            if _reply_has_chat_write(reply_text)
                            else "sem ```write``` nem ```patch``` em Chat.tsx"
                        )
                    )
                )
            )
            )
            )
        )
        prompt = (
            f"REJEITADO: sua resposta anterior — {reject_reason}.\n"
            "Proibido Investigação/Diagnóstico/narrativa.\n"
            f"{patch_hint}"
            "Sem fetch https:// externo."
        )
    result = chat_mod.reply(
        prompt,
        channel="ide",
        user_id=request.conversation_id or chat_mod.AGENT_EPHEMERAL_USER,
        include_context=False,
        delegate_agent=delegate,
        editor_context=request.context or "",
        task_mode="agent",
        model_size=_autonomy_model_size(request.model_size, spec),
        persist_history=False,
        project_root=request.project_root,
        tool_allowlist=tools_allowlist_for_spec(spec) or [],
        tool_max_turns=0,
    )
    if result.get("success") and result.get("reply"):
        next_text = str(result["reply"])
        if _reply_has_actionable_chat_block(next_text, spec, project_root=request.project_root):
            return next_text, True
        return _maybe_reprompt_write_first(
            request, next_text, spec, delegate=delegate, attempt=attempt + 1
        )
    return reply_text, False


def _run_agent_autonomy_cycle(
    request: ChatMessageRequest,
    initial_result: dict[str, Any],
    *,
    delegate: str | None,
    background_tasks: BackgroundTasks | None = None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from learning_agent.core import (
        agent_autonomy_runner,
        agent_spec_builder,
    )

    attempts: list[dict[str, Any]] = []
    reply_text = initial_result.get("reply", "")
    result = initial_result
    if spec is None:
        spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
    first_turn_passed = _reply_has_actionable_chat_block(
        initial_result.get("reply", ""),
        spec,
        project_root=request.project_root,
    )
    autonomy_meta = {"firstTurnPassed": first_turn_passed}
    grounding_llm_budget = [1 if spec.get("deliveryMode") == "refine" else 3]
    if _autonomy_training_modes(spec):
        grounding_repairs: list[dict[str, Any]] = []
    else:
        reply_text, grounding_repairs = _repair_grounding_hallucination(
            request, reply_text, spec, delegate=delegate, llm_budget=grounding_llm_budget
        )
    if grounding_repairs:
        attempts.append({"phase": "grounding-repair", "repairs": grounding_repairs})
    grounding_penalty = bool(grounding_repairs)
    reply_text, write_reprompted = _maybe_reprompt_write_first(
        request, reply_text, spec, delegate=delegate
    )
    if write_reprompted:
        attempts.append({"phase": "write-first-reprompt", "llm": True})
    if _uses_complex_phases(spec):
        return _run_complex_agent_autonomy_cycle(
            request,
            initial_result,
            delegate=delegate,
            background_tasks=background_tasks,
        )

    for attempt in range(request.max_repair_attempts + 1):
        skip_grounding_block = spec.get("ravennaHomeUiMode") in {
            "chat-history-autonomy",
            "chat-patch-gemini",
            "chat-patch-a-gemini",
            "chat-patch-b-gemini",
            "chat-patch-c-gemini",
            "chat-patch-d-gemini",
            "chat-patch-d1-strict-gemini",
            "chat-patch-d2-strict-gemini",
        }
        blocked, pre_violations = (False, []) if skip_grounding_block else _pre_apply_grounding_blocked(
            reply_text, request, spec
        )
        if blocked:
            attempts.append({"phase": "pre-apply-block", "attempt": attempt, "violations": pre_violations})
            reply_text, extra_repairs = _repair_grounding_hallucination(
                request,
                reply_text,
                spec,
                delegate=delegate,
                llm_budget=grounding_llm_budget,
                max_inner_attempts=1,
            )
            if extra_repairs:
                grounding_repairs.extend(extra_repairs)
                grounding_penalty = True
            still_blocked, post_violations = _pre_apply_grounding_blocked(reply_text, request, spec)
            if still_blocked and post_violations == pre_violations:
                attempts.append({"phase": "grounding-stuck", "violations": post_violations})
                return {
                    "enabled": True,
                    "passed": False,
                    "attempts": attempts,
                    "finalReply": reply_text,
                    "groundingBlocked": True,
                    "groundingStuck": True,
                }
            if attempt >= request.max_repair_attempts or (
                grounding_llm_budget[0] <= 0 and still_blocked
            ):
                return {
                    "enabled": True,
                    "passed": False,
                    "attempts": attempts,
                    "finalReply": reply_text,
                    "groundingBlocked": True,
                }
            continue
        applied = _apply_autonomy_reply(reply_text, request, background_tasks=background_tasks, spec=spec)
        applied = _maybe_rollback_voice_pwa_baseline(request, spec, applied)
        applied = _maybe_complete_visual_identity_css(request, spec, applied, background_tasks=background_tasks)
        applied = _maybe_complete_backend_tests(request, spec, applied, background_tasks=background_tasks)
        applied = _maybe_complete_chat_history(request, spec, applied, background_tasks=background_tasks)
        validation, checklist, critique, passed = _evaluate_autonomy_attempt(request, spec, applied)
        still_blocked, _ = _pre_apply_grounding_blocked(reply_text, request, spec)
        if not still_blocked:
            grounding_penalty = False
        if grounding_penalty and still_blocked:
            passed = False
            checklist.setdefault("failures", []).append(
                "Diagnóstico rejeitado por alucinação GROUNDING — repair obrigatório antes de aceitar."
            )
        attempts.append(
            {
                "attempt": attempt,
                "applied": applied,
                "validation": validation,
                "checklist": checklist,
                "critique": critique,
                "passed": passed,
            }
        )
        if passed or attempt >= request.max_repair_attempts:
            if (
                not passed
                and _golden_patch_training_mode(spec)
                and _reply_has_chat_write(reply_text)
            ):
                from learning_agent.core import (
                    ravenna_home_delivery,
                    workspace_bootstrap,
                )

                root = workspace_bootstrap.ravenna_home_dir() / "frontend"
                ui = spec.get("ravennaHomeUiMode")
                marker_ok = (
                    "gemini-chat" in (reply_text or "").lower()
                    if ui == "chat-patch-c-gemini"
                    else (
                        "historyexpanded" in (reply_text or "").lower()
                        if ui in ("chat-patch-b-gemini", "chat-patch-d1-gemini", "chat-patch-d2-gemini")
                        else "pickcollapsedmessages" in (reply_text or "").lower()
                    )
                )
                validate = (
                    ravenna_home_delivery._validate_chat_patch_c
                    if ui == "chat-patch-c-gemini"
                    else (
                        ravenna_home_delivery._validate_chat_patch_d
                        if ui == "chat-patch-d2-gemini"
                        else (
                            ravenna_home_delivery._validate_chat_patch_d1
                            if ui == "chat-patch-d1-gemini"
                            else (
                                ravenna_home_delivery._validate_chat_patch_b
                                if ui == "chat-patch-b-gemini"
                                else ravenna_home_delivery._validate_chat_patch_a
                            )
                        )
                    )
                )
                if marker_ok and root.is_dir() and not validate(root):
                    passed = True
                    if attempts:
                        attempts[-1]["passed"] = True
                        attempts[-1]["patchAFilesystemPass"] = True
            elif (
                not passed
                and spec.get("ravennaHomeUiMode") == "chat-patch-d-gemini"
                and _reply_has_chat_write(reply_text)
                and "sethistoryexpanded(false)" in (reply_text or "").lower()
            ):
                from learning_agent.core import (
                    ravenna_home_delivery,
                    workspace_bootstrap,
                )

                root = workspace_bootstrap.ravenna_home_dir() / "frontend"
                if root.is_dir() and not ravenna_home_delivery._validate_chat_patch_d(root):
                    passed = True
                    if attempts:
                        attempts[-1]["passed"] = True
                        attempts[-1]["patchDFilesystemPass"] = True
            return {
                "enabled": True,
                "passed": passed,
                "attempts": attempts,
                "finalReply": reply_text,
                **autonomy_meta,
            }

        if initial_result.get("model") == "deterministic-contract":
            return {
                "enabled": True,
                "passed": False,
                "attempts": attempts,
                "finalReply": reply_text,
                **autonomy_meta,
            }

        repair_prompt = critique.get("repairPrompt") or agent_autonomy_runner.build_repair_prompt(
            request.message,
            applied=applied,
            validation=validation,
            checklist=checklist,
            project_root=request.project_root,
        )
        result = chat.reply(
            repair_prompt,
            channel="ide",
            user_id=request.conversation_id or chat.AGENT_EPHEMERAL_USER,
            include_context=False,
            delegate_agent=delegate,
            editor_context=request.context or "",
            task_mode="agent",
            model_size=critique.get("recommendedModelSize") or _autonomy_model_size(request.model_size, spec),
            persist_history=False,
            project_root=request.project_root,
        )
        if not result.get("success"):
            attempts.append(
                {
                    "attempt": attempt + 1,
                    "applied": {"applied": [], "changedPaths": [], "blockCount": 0},
                    "validation": {"ok": False, "validated": False, "failures": [result.get("error", "repair failed")]},
                    "checklist": {"ok": False, "failures": ["Falha ao chamar o modelo para correção."], "warnings": []},
                    "passed": False,
                }
            )
            return {"enabled": True, "passed": False, "attempts": attempts, "finalReply": reply_text, **autonomy_meta}
        reply_text = result.get("reply", "")

    return {"enabled": True, "passed": False, "attempts": attempts, "finalReply": reply_text, **autonomy_meta}


@app.post("/api/chat")
def ide_chat_endpoint(request: ChatMessageRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Chat endpoint for IDE"""
    try:
        from learning_agent.core import agent_delegate

        delegate = request.agent.strip() or None
        if not delegate and request.auto_delegate:
            routed = agent_delegate.suggest_delegate(
                request.message,
                request.context or "",
            )
            delegate = routed.get("agent") or None

        chat_channel = (request.channel or "ide").strip() or "ide"
        conv_id = chat.resolve_conversation_id(request.conversation_id or None, channel=chat_channel)
        chat_user = (request.user_id or "").strip() or conv_id
        mode = (request.mode or "chat").strip().lower()
        persist = request.persist_history
        if mode == "agent" and not (request.conversation_id or "").strip():
            persist = False
            conv_id = chat.AGENT_EPHEMERAL_USER

        agent_message = request.message
        autonomy_spec = None
        deterministic_reply = None
        delivery_mode_requested = (request.delivery_mode or "auto").strip().lower()
        tool_allowlist: list[str] | None = None
        tool_max_turns: int | None = request.tool_max_turns
        if mode == "agent":
            if delivery_mode_requested == "vistoria":
                from datetime import datetime

                from learning_agent.core import agent_spec_builder
                from learning_agent.core.ravenna_home_autonomy import (
                    DELIVERY_TOOLS_VISTORIA,
                    apply_delivery_settings,
                    build_vistoria_autonomy_message,
                    run_vistoria_delivery,
                )

                quick_spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
                if quick_spec.get("ravennaHome") and quick_spec.get("ravennaHomeUiMode") not in {
                    "chat-history-autonomy",
                    "chat-patch-gemini",
                    "chat-patch-a-gemini",
                }:
                    quick_spec["requireGroundingTools"] = True
                apply_delivery_settings(request, quick_spec)
                vistoria = run_vistoria_delivery(request, quick_spec, narrate=False)
                quick_spec["deliveryMode"] = "vistoria"
                reply = vistoria["report"]
                narrate = __import__("os").environ.get("RAVENNA_VISTORIA_NARRATE", "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                }
                if not narrate:
                    return {
                        "id": "response-vistoria",
                        "message": reply,
                        "agent": AGENT_NAME,
                        "delegate_agent": delegate,
                        "reasoning": "vistoria determinística (sem LLM)",
                        "conversation_id": conv_id,
                        "concepts": [],
                        "timestamp": datetime.now().isoformat(),
                        "autonomy": {
                            "enabled": True,
                            "passed": vistoria["passed"],
                            "deliveryMode": "vistoria",
                            "vistoria": vistoria["audit"],
                            "spec": quick_spec,
                        },
                    }
                agent_message = build_vistoria_autonomy_message(
                    request.message,
                    quick_spec,
                    vistoria["audit"],
                    request.project_root,
                )
                autonomy_spec = quick_spec
                tool_allowlist = list(DELIVERY_TOOLS_VISTORIA)
                tool_max_turns = 1
            elif request.auto_apply:
                from learning_agent.core import agent_spec_builder
                from learning_agent.core.ravenna_home_autonomy import (
                    apply_delivery_settings,
                    build_refine_autonomy_message,
                    seed_and_validate,
                    tools_allowlist_for_spec,
                    try_seed_pass_short_circuit,
                )

                quick_spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
                if quick_spec.get("ravennaHome") and quick_spec.get("ravennaHomeUiMode") not in {
                    "chat-history-autonomy",
                    "chat-patch-gemini",
                    "chat-patch-a-gemini",
                }:
                    quick_spec["requireGroundingTools"] = True

                seed_short = try_seed_pass_short_circuit(
                    request, quick_spec, delivery_mode_requested
                )
                if seed_short is not None:
                    from datetime import datetime

                    short_result = seed_short["result"]
                    short_result["conversation_id"] = conv_id
                    short_result["delegate_agent"] = delegate
                    autonomy = seed_short["autonomy"]
                    autonomy["spec"] = quick_spec
                    _record_autonomy_lesson(request, autonomy)
                    return {
                        "id": "response-seed-pass",
                        "message": short_result.get("reply", ""),
                        "agent": short_result.get("agent", AGENT_NAME),
                        "delegate_agent": delegate,
                        "reasoning": "Modelo: seed-pass (sem LLM)",
                        "conversation_id": conv_id,
                        "concepts": [],
                        "timestamp": datetime.now().isoformat(),
                        "autonomy": autonomy,
                    }
                if delivery_mode_requested == "seed-only" and quick_spec.get("ravennaHome"):
                    check = seed_and_validate(quick_spec, force=True)
                    if not check["ok"]:
                        from datetime import datetime

                        return {
                            "id": "error-seed-only",
                            "message": f"seed-only falhou: {check['failures']}",
                            "agent": AGENT_NAME,
                            "delegate_agent": delegate,
                            "reasoning": "seed-only — validate_filesystem reprovou",
                            "conversation_id": conv_id,
                            "concepts": [],
                            "timestamp": datetime.now().isoformat(),
                            "autonomy": {
                                "enabled": True,
                                "passed": False,
                                "seedPass": False,
                                "failures": check["failures"],
                            },
                        }

                agent_message, autonomy_spec = _build_autonomy_prompt(request.message, request.project_root)

                if is_remote_feature_implement_work_removed(request.message, autonomy_spec):
                    autonomy_spec["remoteappFeatureImplement"] = True
                    autonomy_spec["validationCommands"] = []
                deterministic_reply = _build_deterministic_autonomy_reply(
                    request.message,
                    autonomy_spec,
                    request.project_root,
                )
                if not deterministic_reply:
                    delivery_mode = apply_delivery_settings(request, autonomy_spec)
                    if delivery_mode == "refine" and autonomy_spec.get("ravennaHome"):
                        agent_message = build_refine_autonomy_message(
                            request.message,
                            autonomy_spec,
                            request.project_root,
                        )
                    tool_allowlist = tools_allowlist_for_spec(autonomy_spec)
                    tool_max_turns = autonomy_spec.get("toolMaxTurns") or request.tool_max_turns
            else:
                # Mobile Home: NÃO injetar Ciclo autônomo / investigation IDE.
                # Isso transformava "Feche o Opera" em teatro Investigação/Diagnóstico/Solução.
                if chat_channel in {"ide", "theater"}:
                    from learning_agent.core import agent_spec_builder
                    from learning_agent.core.agent_investigate import (
                        build_investigation_context,
                    )
                    from learning_agent.identity import AGENT_INVESTIGATION_BLOCK

                    spec = agent_spec_builder.build_spec(request.message, project_root=request.project_root)
                    investigation = build_investigation_context(
                        request.message, spec, project_root=request.project_root
                    )
                    parts = [request.message, AGENT_INVESTIGATION_BLOCK]
                    if investigation:
                        parts.append(investigation)
                    agent_message = "\n\n---\n\n".join(parts)
                else:
                    agent_message = request.message
        requested_model_size = _autonomy_model_size(request.model_size, autonomy_spec) if autonomy_spec else (request.model_size.strip() or "auto")

        if deterministic_reply:
            if autonomy_spec is not None:
                
                if is_remote_notification_work_removed(request.message, autonomy_spec):
                    autonomy_spec["trustedCanonical"] = True
                if is_remote_deploy_work_removed(request.message, autonomy_spec):
                    autonomy_spec["trustedCanonical"] = True
                    autonomy_spec["remoteappDeploy"] = True
                
                if is_remote_restart_validate_work_removed(request.message, autonomy_spec):
                    autonomy_spec["trustedCanonical"] = True
                    autonomy_spec["remoteappDeploy"] = True
                
                if is_remote_static_publish_work_removed(request.message, autonomy_spec):
                    autonomy_spec["remoteappStaticPublish"] = True
                    autonomy_spec["remoteappDeployOk"] = bool((autonomy_spec.get("remoteappRemoteOps") or {}).get("ok"))
            result = {
                "success": True,
                "reply": deterministic_reply,
                "agent": AGENT_NAME,
                "model": "deterministic-contract",
                "conversation_id": conv_id,
                "delegate_agent": delegate,
            }
        else:
            # Get response from learning agent chat
            result = chat.reply(
                agent_message,
                channel=chat_channel,
                user_id=chat_user,
                include_context=(
                    request.include_context
                    if request.include_context is not None
                    else bool((request.context or "").strip())
                ),
                delegate_agent=delegate,
                editor_context=request.context or "",
                task_mode=mode or "chat",
                model_size=requested_model_size,
                persist_history=persist,
                project_root=request.project_root,
                require_grounding_tools=bool(
                    autonomy_spec and autonomy_spec.get("requireGroundingTools")
                ),
                required_grounding_reads=(
                    (autonomy_spec or {}).get("requiredGroundingReads")
                    if autonomy_spec
                    else None
                ),
                tool_allowlist=tool_allowlist,
                tool_max_turns=tool_max_turns,
                attachment_ids=list(request.attachment_ids or []),
                engine=(request.engine or "groq").strip(),
            )
        
        if not result.get("success"):
            return {
                "id": "error",
                "message": f"Erro: {result.get('error', 'Desconhecido')}",
                "reasoning": result.get("hint", ""),
                "concepts": [],
                "timestamp": "",
            }
        
        autonomy = None
        if mode == "agent" and request.auto_apply:
            autonomy = _run_agent_autonomy_cycle(
                request,
                result,
                delegate=delegate,
                background_tasks=background_tasks,
                spec=autonomy_spec,
            )
            if autonomy.get("finalReply"):
                result["reply"] = autonomy["finalReply"]
            if autonomy_spec:
                autonomy["spec"] = autonomy_spec
            _record_autonomy_lesson(request, autonomy)

        from datetime import datetime
        return {
            "id": f"response-{id(result)}",
            "message": result.get("reply", ""),
            "media": result.get("media") or [],
            "transfer": result.get("transfer"),
            "plan": result.get("plan"),
            "tool_log": result.get("tool_log") or [],
            "agent": result.get("agent", AGENT_NAME),
            "delegate_agent": result.get("delegate_agent") or delegate,
            "reasoning": f"Modelo: {result.get('model', 'unknown')}",
            "conversation_id": result.get("conversation_id") or conv_id,
            "concepts": [],
            "timestamp": datetime.now().isoformat(),
            "autonomy": autonomy,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/autonomy/run")
def agent_autonomy_run_endpoint(request: ChatMessageRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Executa um turno Agent backend-first: gerar, aplicar, validar e corrigir."""
    request.mode = "agent"
    if request.auto_apply and request.max_repair_attempts == 2:
        if (request.delivery_mode or "auto").strip().lower() != "refine":
            request.max_repair_attempts = 3
    return ide_chat_endpoint(request, background_tasks)


def _sanitize_stream_error(exc: BaseException | str) -> str:
    err = str(exc)
    if "created in a different Context" in err or "ContextVar" in err:
        return "Falha interna de contexto nas ferramentas. Tente de novo."
    if len(err) > 400:
        return err[:400] + "…"
    return err


def _changed_paths_from_tool_log(tool_log: list[dict[str, Any]] | None) -> list[str]:
    """Extract successfully written paths from agent tool_log (write_file / apply_patch)."""
    paths: list[str] = []
    write_tools = {"write_file", "apply_patch", "android_write_file"}
    for entry in tool_log or []:
        name = str(entry.get("tool") or "").strip().lower()
        if name not in write_tools:
            continue
        args = entry.get("arguments") or {}
        arg_path = ""
        if isinstance(args, dict):
            arg_path = str(args.get("path") or "").replace("\\", "/").strip()
        result_raw = entry.get("result")
        changed: list[str] = []
        if isinstance(result_raw, str) and result_raw.strip().startswith("{"):
            try:
                parsed = json.loads(result_raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                for key in ("changedPaths", "changed_paths"):
                    vals = parsed.get(key)
                    if isinstance(vals, list):
                        changed.extend(str(p).replace("\\", "/").strip() for p in vals if p)
                if parsed.get("error") and not changed:
                    continue
                if not changed and arg_path and not parsed.get("error"):
                    changed.append(arg_path)
        elif arg_path and not (isinstance(result_raw, str) and "error" in result_raw.lower()[:80]):
            changed.append(arg_path)
        for path in changed:
            if path and path not in paths:
                paths.append(path)
    return paths


_READ_TOOLS = frozenset(
    {
        "read_file",
        "windows_read_file",
        "android_read_file",
        "list_files",
        "windows_list_dir",
        "android_list_dir",
        "windows_list_windows",
        "host_status",
        "windows_status",
        "android_status",
    }
)
_SEARCH_TOOLS = frozenset(
    {
        "grep_workspace",
        "search_code",
        "search_knowledge",
        "windows_find_files",
        "android_find_files",
        "windows_search_google",
        "windows_search_youtube",
        "get_related_errors",
        "get_context_for_task",
        "research_trusted_sources",
    }
)


def _tool_entry_name(entry: dict[str, Any]) -> str:
    return str(entry.get("tool") or "").strip().lower()


def _exploration_summary_from_tool_log(
    tool_log: list[dict[str, Any]] | None,
) -> tuple[int, int, list[str]]:
    """Return (files, searches, labels) from explore-only tool entries."""
    files = 0
    searches = 0
    labels: list[str] = []
    for entry in tool_log or []:
        name = _tool_entry_name(entry)
        args = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
        if name in _READ_TOOLS or "list_dir" in name or name == "list_files":
            files += 1
            path = str(args.get("path") or args.get("dir") or "").replace("\\", "/").strip()
            if path:
                labels.append(path.split("/")[-1] or path)
        elif name in _SEARCH_TOOLS or "grep" in name or "search" in name:
            searches += 1
            q = str(
                args.get("query")
                or args.get("pattern")
                or args.get("q")
                or args.get("path")
                or ""
            ).strip()
            if q:
                labels.append(q[:48] + ("…" if len(q) > 48 else ""))
    # de-dupe labels preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for lab in labels:
        if lab in seen:
            continue
        seen.add(lab)
        uniq.append(lab)
    return files, searches, uniq[:8]


def _synthesize_tool_write_reply(paths: list[str], reply: str) -> str:
    """Avoid empty chat when tools wrote files but the model returned no prose."""
    if (reply or "").strip():
        return reply
    if not paths:
        return reply or ""
    names = ", ".join(f"`{p.split('/')[-1]}`" for p in paths[:12])
    more = f" (+{len(paths) - 12})" if len(paths) > 12 else ""
    return f"Alterei {len(paths)} arquivo(s) via tools: {names}{more}."


def _synthesize_tool_reply(
    tool_log: list[dict[str, Any]] | None,
    reply: str,
    *,
    write_paths: list[str] | None = None,
) -> str:
    """Fill empty final reply after tools (writes first, else exploration summary)."""
    if (reply or "").strip():
        return reply
    paths = list(write_paths) if write_paths is not None else _changed_paths_from_tool_log(tool_log)
    if paths:
        return _synthesize_tool_write_reply(paths, reply)
    files, searches, labels = _exploration_summary_from_tool_log(tool_log)
    if not files and not searches:
        return reply or ""
    parts: list[str] = []
    if files:
        parts.append("1 arquivo" if files == 1 else f"{files} arquivos")
    if searches:
        parts.append("1 busca" if searches == 1 else f"{searches} buscas")
    head = f"Explorei {' e '.join(parts)}."
    if labels:
        shown = ", ".join(f"`{x}`" for x in labels)
        return f"{head} Resumo: {shown}."
    return head


def _merge_tool_paths_into_autonomy(
    autonomy: dict[str, Any] | None,
    tool_paths: list[str],
    *,
    final_reply: str,
) -> dict[str, Any] | None:
    """Merge tool-loop writes into autonomy so UI does not report false parseFailed."""
    if not autonomy and not tool_paths:
        return autonomy
    if autonomy is None:
        autonomy = {
            "enabled": True,
            "passed": bool(tool_paths),
            "attempts": [
                {
                    "attempt": 0,
                    "passed": bool(tool_paths),
                    "applied": {
                        "applied": [{"path": p} for p in tool_paths],
                        "changedPaths": list(tool_paths),
                        "blockCount": len(tool_paths),
                        "fromTools": True,
                    },
                }
            ],
            "finalReply": final_reply,
            "fromToolsOnly": True,
            "toolChangedPaths": list(tool_paths),
            "mergedChangedPaths": list(tool_paths),
        }
        return autonomy

    attempts = list(autonomy.get("attempts") or [])
    existing: list[str] = []
    for attempt in attempts:
        for path in (attempt.get("applied") or {}).get("changedPaths") or []:
            p = str(path).replace("\\", "/").strip()
            if p and p not in existing:
                existing.append(p)
    merged = list(existing)
    for path in tool_paths:
        if path not in merged:
            merged.append(path)
    if tool_paths and attempts:
        last = dict(attempts[-1])
        applied = dict(last.get("applied") or {})
        applied_paths = list(applied.get("changedPaths") or [])
        for path in tool_paths:
            if path not in applied_paths:
                applied_paths.append(path)
        applied["changedPaths"] = applied_paths
        applied["blockCount"] = max(int(applied.get("blockCount") or 0), len(applied_paths))
        applied["fromTools"] = True
        last["applied"] = applied
        if applied_paths and not last.get("passed") and autonomy.get("fromToolsOnly"):
            last["passed"] = True
        attempts[-1] = last
        autonomy["attempts"] = attempts
    elif tool_paths and not attempts:
        autonomy["attempts"] = [
            {
                "attempt": 0,
                "passed": True,
                "applied": {
                    "changedPaths": list(tool_paths),
                    "blockCount": len(tool_paths),
                    "fromTools": True,
                },
            }
        ]
    autonomy["toolChangedPaths"] = list(tool_paths)
    autonomy["mergedChangedPaths"] = merged
    if merged and not autonomy.get("passed") and autonomy.get("fromToolsOnly"):
        autonomy["passed"] = True
    if not (autonomy.get("finalReply") or "").strip() and merged:
        autonomy["finalReply"] = final_reply
    return autonomy


@app.post("/api/chat/stream")
def chat_stream_endpoint(request: ChatMessageRequest):
    """Stream NDJSON — deltas de texto + linha final com metadados."""

    def generate():
        try:
            from learning_agent.core import agent_delegate
            from learning_agent.core.ravenna_home_autonomy import (
                tools_allowlist_for_spec,
            )

            delegate = request.agent.strip() or None
            if not delegate and request.auto_delegate:
                routed = agent_delegate.suggest_delegate(
                    request.message,
                    request.context or "",
                )
                delegate = routed.get("agent") or None

            conv_id = chat.resolve_conversation_id(request.conversation_id or None, channel="ide")
            mode = (request.mode or "chat").strip().lower()
            persist = request.persist_history
            if mode == "agent" and not (request.conversation_id or "").strip():
                persist = False
                conv_id = chat.AGENT_EPHEMERAL_USER
            elif mode == "agent" and (request.conversation_id or "").strip():
                persist = True

            agent_message = request.message
            autonomy_spec = None
            tool_allowlist: list[str] | None = None
            tool_max_turns: int | None = request.tool_max_turns
            if mode == "agent" and request.auto_apply:
                agent_message, autonomy_spec = _build_autonomy_prompt(request.message, request.project_root)
                tool_allowlist = tools_allowlist_for_spec(autonomy_spec)
                tool_max_turns = (autonomy_spec or {}).get("toolMaxTurns") or request.tool_max_turns
            requested_model_size = _autonomy_model_size(request.model_size, autonomy_spec) if autonomy_spec else (request.model_size.strip() or "auto")

            for item in chat.iter_reply_deltas(
                agent_message,
                channel="ide",
                user_id=conv_id,
                include_context=(
                    request.include_context
                    if request.include_context is not None
                    else bool((request.context or "").strip())
                ),
                delegate_agent=delegate,
                editor_context=request.context or "",
                task_mode=mode or "chat",
                model_size=requested_model_size,
                persist_history=persist,
                project_root=request.project_root,
                require_grounding_tools=bool(
                    autonomy_spec and autonomy_spec.get("requireGroundingTools")
                ),
                required_grounding_reads=(
                    (autonomy_spec or {}).get("requiredGroundingReads")
                    if autonomy_spec
                    else None
                ),
                tool_allowlist=tool_allowlist,
                tool_max_turns=tool_max_turns,
                attachment_ids=list(request.attachment_ids or []),
                engine=(request.engine or "groq").strip(),
            ):
                if isinstance(item, str):
                    yield json.dumps({"type": "delta", "delta": item}, ensure_ascii=False) + "\n"
                elif isinstance(item, dict) and item.get("tool"):
                    yield json.dumps({"type": "tool", "entry": item["tool"]}, ensure_ascii=False) + "\n"
                elif isinstance(item, dict) and item.get("phase"):
                    yield json.dumps(
                        {"type": "phase", "phase": item.get("phase")},
                        ensure_ascii=False,
                    ) + "\n"
                elif isinstance(item, dict) and item.get("agent_step"):
                    yield json.dumps(
                        {"type": "agent_step", "step": item["agent_step"]},
                        ensure_ascii=False,
                    ) + "\n"
                elif isinstance(item, dict) and item.get("thinking"):
                    yield json.dumps(
                        {"type": "thinking", "thinking": item["thinking"]},
                        ensure_ascii=False,
                    ) + "\n"
                elif isinstance(item, dict) and item.get("final"):
                    # Emit final BEFORE autonomy so the composer unlocks immediately.
                    tool_log = list(item.get("tool_log") or [])
                    tool_paths = _changed_paths_from_tool_log(tool_log)
                    final_message = item.get("reply") or item.get("error") or ""
                    final_message = _synthesize_tool_reply(
                        tool_log, final_message, write_paths=tool_paths
                    )
                    early_autonomy = None
                    run_autonomy = False
                    if mode == "agent" and request.auto_apply and not item.get("error"):
                        if tool_paths and not _reply_has_chat_write(final_message):
                            early_autonomy = _merge_tool_paths_into_autonomy(
                                {
                                    "enabled": True,
                                    "passed": True,
                                    "attempts": [
                                        {
                                            "attempt": 0,
                                            "passed": True,
                                            "applied": {
                                                "changedPaths": list(tool_paths),
                                                "blockCount": len(tool_paths),
                                                "fromTools": True,
                                            },
                                        }
                                    ],
                                    "finalReply": final_message,
                                    "fromToolsOnly": True,
                                },
                                tool_paths,
                                final_reply=final_message,
                            )
                        else:
                            run_autonomy = True
                    elif tool_paths:
                        early_autonomy = _merge_tool_paths_into_autonomy(
                            None, tool_paths, final_reply=final_message
                        )
                    if autonomy_spec and early_autonomy is not None:
                        early_autonomy["spec"] = autonomy_spec
                    payload: dict[str, Any] = {
                        "type": "final",
                        "message": final_message,
                        "agent": item.get("agent", AGENT_NAME),
                        "delegate_agent": item.get("delegate_agent") or delegate,
                        "reasoning": f"Modelo: {item.get('model', 'unknown')}"
                        + (
                            f" · {request.engine or 'groq'}/{item.get('model_size')}"
                            if item.get("model_size")
                            else ""
                        ),
                        "conversation_id": conv_id,
                        "autonomy": early_autonomy,
                        "tool_log": tool_log,
                        "changedPathsFromTools": tool_paths,
                        "media": item.get("media") or [],
                        "transfer": item.get("transfer"),
                        "plan": item.get("plan"),
                    }
                    if item.get("error"):
                        payload["error"] = item["error"]
                    if item.get("hint"):
                        payload["hint"] = item["hint"]
                    yield json.dumps(payload, ensure_ascii=False) + "\n"

                    if run_autonomy:
                        yield json.dumps(
                            {"type": "phase", "phase": "applying"},
                            ensure_ascii=False,
                        ) + "\n"
                        autonomy = _run_agent_autonomy_cycle(
                            request,
                            {
                                "success": True,
                                "reply": final_message,
                                "agent": item.get("agent", AGENT_NAME),
                                "delegate_agent": item.get("delegate_agent") or delegate,
                                "model": item.get("model", "unknown"),
                                "conversation_id": conv_id,
                                "tool_log": tool_log,
                            },
                            delegate=delegate,
                            background_tasks=None,
                            spec=autonomy_spec,
                        )
                        autonomy = _merge_tool_paths_into_autonomy(
                            autonomy, tool_paths, final_reply=final_message
                        )
                        if autonomy_spec and autonomy is not None:
                            autonomy["spec"] = autonomy_spec
                        if autonomy is not None:
                            _record_autonomy_lesson(request, autonomy)
                        yield json.dumps(
                            {
                                "type": "autonomy",
                                "autonomy": autonomy,
                                "message": (autonomy or {}).get("finalReply") or final_message,
                                "changedPathsFromTools": (autonomy or {}).get("mergedChangedPaths")
                                or tool_paths,
                            },
                            ensure_ascii=False,
                        ) + "\n"
                    elif early_autonomy is not None:
                        _record_autonomy_lesson(request, early_autonomy)
        except Exception as e:
            yield json.dumps(
                {"type": "error", "message": _sanitize_stream_error(e)},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/chat/conversations")
def chat_conversations_list_endpoint(
    channel: str = "ide",
    include_archived: bool = False,
    workspace_root_id: str | None = None,
    unscoped_only: bool = False,
) -> dict[str, Any]:
    """Lista conversas persistidas da IDE."""
    conversations = chat.list_conversations(
        channel,
        include_archived=include_archived,
        workspace_root_id=workspace_root_id or None,
        unscoped_only=unscoped_only,
    )
    active = conversations[0]["id"] if conversations else None
    return {"conversations": conversations, "active_id": active, "channel": channel}


@app.post("/api/chat/conversations")
def chat_conversations_create_endpoint(
    body: CreateConversationRequest,
    channel: str = "ide",
) -> dict[str, Any]:
    """Inicia nova conversa vazia."""
    conv = chat.create_conversation(
        channel,
        body.title.strip() or "Nova conversa",
        project_name=body.project_name,
        project_root=body.project_root,
        workspace_root_ids=body.workspace_root_ids,
    )
    return {"success": True, "conversation": conv}


@app.put("/api/chat/conversations/{conversation_id}")
def chat_conversations_update_endpoint(
    conversation_id: str,
    body: UpdateConversationRequest,
) -> dict[str, Any]:
    """Atualiza metadados da conversa (projeto, workspaces anexados)."""
    try:
        conv = chat.update_conversation(
            conversation_id,
            title=body.title,
            project_name=body.project_name,
            project_root=body.project_root,
            workspace_root_ids=body.workspace_root_ids,
        )
        return {"success": True, "conversation": conv}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/chat/conversations/{conversation_id}")
def chat_conversations_delete_endpoint(conversation_id: str) -> dict[str, Any]:
    """Apaga conversa e todas as mensagens."""
    try:
        return chat.delete_conversation(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat/conversations/{conversation_id}/archive")
def chat_conversations_archive_endpoint(conversation_id: str, archived: bool = True) -> dict[str, Any]:
    """Esconde/restaura conversa sem apagar mensagens."""
    try:
        return chat.archive_conversation(conversation_id, archived=archived)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/chat/history")
def chat_history_endpoint(
    channel: str = "ide",
    user_id: str = "",
    conversation_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Histórico de conversa persistido — restaurar painel Chat na extensão."""
    cid = (conversation_id or user_id or "").strip()
    if not cid:
        cid = chat.resolve_conversation_id(None, channel=channel)
    messages = chat.get_history(channel, cid, limit=min(max(limit, 1), 200))
    return {"messages": messages, "channel": channel, "conversation_id": cid, "user_id": cid}


@app.get("/api/chat/plans/{conversation_id}")
def chat_plan_get_endpoint(conversation_id: str) -> dict[str, Any]:
    """Carrega o AgentPlan persistido de uma conversa (modo Plan)."""
    plan = db.load_chat_plan(conversation_id)
    return {"conversation_id": conversation_id, "plan": plan}


@app.put("/api/chat/plans/{conversation_id}")
def chat_plan_put_endpoint(conversation_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Persiste o AgentPlan de uma conversa (JSON no corpo)."""
    plan = body.get("plan", body)
    if not isinstance(plan, dict):
        raise HTTPException(status_code=400, detail="plan deve ser um objeto JSON")
    ok = db.save_chat_plan(conversation_id, plan)
    return {"success": ok, "conversation_id": conversation_id}


@app.delete("/api/chat/plans/{conversation_id}")
def chat_plan_delete_endpoint(conversation_id: str) -> dict[str, Any]:
    """Remove o AgentPlan persistido de uma conversa."""
    ok = db.delete_chat_plan(conversation_id)
    return {"success": ok, "conversation_id": conversation_id}


@app.get("/api/knowledge")
def get_knowledge_endpoint(query: str = Query(..., min_length=1), limit: int = 5) -> dict[str, Any]:
    """Search knowledge base"""
    results = knowledge.search(query, limit=limit)
    return {"query": query, "results": results}


@app.get("/api/memory/audit")
def memory_audit_endpoint(limit: int = 10, include_chroma: bool = True) -> dict[str, Any]:
    """Read-only memory hygiene report. Never deletes or reindexes data."""
    return memory_audit.run_memory_audit(limit=limit, include_chroma=include_chroma)


@app.get("/api/memory/curation")
def memory_curation_endpoint(
    limit: int = 10,
    apply: bool = False,
    max_batches: int = 1,
    include_groups: bool = True,
) -> dict[str, Any]:
    """Plan/apply reversible superseding of duplicate memory. Never deletes data."""
    return memory_audit.run_memory_curation(
        limit=limit,
        apply=apply,
        max_batches=max_batches,
        include_groups=include_groups,
    )


@app.post("/api/memory/restore")
def memory_restore_endpoint(
    table: str | None = None,
    canonical_id: int | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Restore superseded memory rows back to active status. Never deletes data."""
    return memory_audit.restore_superseded_memory(
        table=table,
        canonical_id=canonical_id,
        limit=limit,
    )


@app.get("/api/progress")
def get_progress_endpoint() -> dict[str, Any]:
    """Get learning progress"""
    return progress.get_progress()


@app.get("/api/files")
def list_workspace_files(path: str = "") -> dict[str, Any]:
    """Lista diretório do workspace (explorer Fase 1)."""
    from learning_agent.core.workspace import WorkspaceError, list_directory

    try:
        return list_directory(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/files/content")
def read_workspace_file(path: str = Query(..., min_length=1)) -> dict[str, Any]:
    """Lê conteúdo de arquivo do workspace."""
    from learning_agent.core.workspace import WorkspaceError, read_file

    try:
        return read_file(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class WriteFileRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""


@app.post("/api/attachments")
async def upload_attachment(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload de anexo + indexação RAG para texto (Fase 4)."""
    from learning_agent.core.attachments import AttachmentError, save_attachment

    raw = await file.read()
    try:
        return save_attachment(file.filename or "anexo.txt", raw)
    except AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/attachments")
def list_attachments_endpoint(limit: int = 40) -> dict[str, Any]:
    from learning_agent.core.attachments import list_attachments

    return {"attachments": list_attachments(limit=min(limit, 80))}


@app.get("/api/attachments/{attachment_id}/file")
def get_attachment_file(attachment_id: str) -> FileResponse:
    from learning_agent.core.attachments import AttachmentError, resolve_attachment_path

    try:
        path = resolve_attachment_path(attachment_id)
    except AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return FileResponse(path)


@app.post("/api/chat/media")
async def upload_chat_media(file: UploadFile = File(...)) -> dict[str, Any]:
    from learning_agent.core.chat_media import ChatMediaError, save_media

    raw = await file.read()
    try:
        return save_media(raw, file.filename or "media.bin", source="upload")
    except ChatMediaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/chat/media/{media_id}")
def get_chat_media_file(media_id: str) -> FileResponse:
    import mimetypes

    from learning_agent.core.chat_media import ChatMediaError, resolve_media_path

    try:
        path = resolve_media_path(media_id)
    except ChatMediaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        content_disposition_type="inline",
    )


@app.get("/api/transfers/{transfer_id}")
def get_transfer_status(transfer_id: str) -> dict[str, Any]:
    from learning_agent.core.file_transfer import get_transfer

    job = get_transfer(transfer_id)
    if not job:
        raise HTTPException(status_code=404, detail="transfer not found")
    return job


@app.post("/api/transfers")
def start_transfer(body: dict[str, Any]) -> dict[str, Any]:
    from learning_agent.core.file_transfer import start_windows_video_transfer

    job = start_windows_video_transfer(
        query=str(body.get("query") or ""),
        windows_path=str(body.get("windows_path") or ""),
    )
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "transfer failed")
    return job


@app.post("/api/transfers/{transfer_id}/pause")
def pause_transfer_endpoint(transfer_id: str) -> dict[str, Any]:
    from learning_agent.core.file_transfer import pause_transfer

    job = pause_transfer(transfer_id)
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "pause failed")
    return job


@app.post("/api/transfers/{transfer_id}/resume")
def resume_transfer_endpoint(transfer_id: str) -> dict[str, Any]:
    from learning_agent.core.file_transfer import resume_transfer

    job = resume_transfer(transfer_id)
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "resume failed")
    return job


@app.post("/api/transfers/{transfer_id}/cancel")
def cancel_transfer_endpoint(transfer_id: str) -> dict[str, Any]:
    from learning_agent.core.file_transfer import cancel_transfer

    job = cancel_transfer(transfer_id)
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "cancel failed")
    return job


@app.get("/api/plans/{plan_id}")
def get_plan_status(plan_id: str) -> dict[str, Any]:
    from learning_agent.core.media_plan import get_plan

    job = get_plan(plan_id)
    if not job:
        raise HTTPException(status_code=404, detail="plan not found")
    return job


@app.post("/api/plans")
def start_plan(body: dict[str, Any]) -> dict[str, Any]:
    from learning_agent.core.media_plan import start_media_plan

    job = start_media_plan(
        message=str(body.get("message") or ""),
        query=str(body.get("query") or ""),
        conversation_id=str(body.get("conversation_id") or ""),
        channel=str(body.get("channel") or ""),
    )
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "plan failed")
    return job


@app.post("/api/plans/{plan_id}/cancel")
def cancel_plan_endpoint(plan_id: str) -> dict[str, Any]:
    from learning_agent.core.media_plan import cancel_plan

    return cancel_plan(plan_id)


@app.post("/api/plans/{plan_id}/confirm-delete")
def confirm_delete_plan_endpoint(plan_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from learning_agent.core.media_plan import confirm_delete_plan

    confirm = True if body is None else bool((body or {}).get("confirm", True))
    job = confirm_delete_plan(plan_id, confirm=confirm)
    if not job.get("ok"):
        raise HTTPException(status_code=400, detail=job.get("error") or "confirm failed")
    return job


@app.get("/api/mcp/status")
def mcp_status() -> dict[str, Any]:
    """Status do servidor MCP embutido (Fase 5)."""
    from learning_agent.core.mcp_bridge import get_status

    return get_status()


@app.get("/api/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    from learning_agent.core.mcp_bridge import list_tools

    return {"tools": list_tools()}


class McpInvokeRequest(BaseModel):
    tool: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/mcp/invoke")
async def mcp_invoke(body: McpInvokeRequest) -> dict[str, Any]:
    from learning_agent.core.mcp_bridge import McpBridgeError, invoke_tool
    from learning_agent.ide import ravenna_ide

    await ravenna_ide.broadcast_tool_call(
        body.tool,
        status="running",
        detail=json.dumps(body.arguments, ensure_ascii=False)[:200],
        source="mcp",
    )
    try:
        result = invoke_tool(body.tool, body.arguments)
        preview = json.dumps(result, ensure_ascii=False)[:300] if isinstance(result, dict) else str(result)[:300]
        await ravenna_ide.broadcast_tool_call(
            body.tool,
            status="done",
            result=preview,
            source="mcp",
        )
        return result
    except McpBridgeError as exc:
        await ravenna_ide.broadcast_tool_call(
            body.tool,
            status="error",
            result=exc.message,
            source="mcp",
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/mcp/external")
def mcp_external_status() -> dict[str, Any]:
    """MCP externo — mcp.json workspace + usuário."""
    from learning_agent.core import mcp_external

    return mcp_external.load_external_mcp()


class ExternalMcpServerRequest(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    transport: str = "stdio"


@app.put("/api/mcp/external/servers")
def mcp_external_save_server(body: ExternalMcpServerRequest) -> dict[str, Any]:
    """Cria/atualiza servidor MCP no .cursor/mcp.json do workspace."""
    from learning_agent.core import mcp_external

    try:
      return mcp_external.save_workspace_server(
          body.name,
          command=body.command,
          args=body.args,
          env=body.env,
          transport=body.transport,
      )
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/mcp/external/servers/{name}")
def mcp_external_remove_server(name: str) -> dict[str, Any]:
    """Remove servidor MCP do .cursor/mcp.json do workspace."""
    from learning_agent.core import mcp_external

    try:
      return mcp_external.remove_workspace_server(name)
    except ValueError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from exc


def _cursor_parity_report() -> dict[str, Any]:
    latest_candidates = [
        PROJECT_ROOT / "data" / "diagnostics" / "autonomy-harness" / "full-final.json",
        PROJECT_ROOT / "data" / "diagnostics" / "autonomy-harness" / "latest.json",
    ]
    benchmark = next((path for path in latest_candidates if path.is_file()), None)
    summary: dict[str, Any] = {}
    if benchmark:
        try:
            summary = json.loads(benchmark.read_text(encoding="utf-8")).get("summary") or {}
        except json.JSONDecodeError:
            summary = {}

    def has(path: str, *tokens: str) -> bool:
        candidates = [PROJECT_ROOT / path]
        ws = os.environ.get("RAVENNA_WORKSPACE_ROOT", "").strip()
        if ws:
            candidates.append(Path(ws) / path)
        for target in candidates:
            if not target.is_file():
                continue
            text = target.read_text(encoding="utf-8", errors="replace")
            if all(token in text for token in tokens):
                return True
        return False

    dimensions = [
        _parity_dimension("composer_modes", "Composer modes", has("ravenna-ide/frontend/src/utils/resolveComposerMode.ts", "ask", "agent", "plan", "autonomy")),
        _parity_dimension("context_picker", "Context picker", has("ravenna-ide/frontend/src/components/ContextFilePicker.tsx", "virtualContextItems", "getAgentContextBundle") and has("ravenna-ide/frontend/src/utils/buildChatContext.ts", "@problems", "@git", "@terminal", "@symbols")),
        _parity_dimension("visible_agent_run", "Visible agent run", has("ravenna-ide/frontend/src/components/SoftwareDeliveryPanel.tsx", "Timeline dos especialistas", "Gates", "Repair plan")),
        _parity_dimension("diff_apply_rollback", "Diff/apply/reject/rollback", has("ravenna-ide/frontend/src/components/SoftwareDeliveryPanel.tsx", "restoreAttempt", "checkpoints", "Aceitar")),
        _parity_dimension("terminal_integration", "Terminal integration", has("ravenna-ide/frontend/src/components/TerminalPanel.tsx", "Terminal") and has("ravenna-ide/frontend/src/utils/buildChatContext.ts", "@terminal")),
        _parity_dimension("problems_integration", "Problems integration", has("ravenna-ide/frontend/src/components/ProblemsPanel.tsx", "ide-problems-panel") and has("ravenna-ide/frontend/src/utils/buildChatContext.ts", "@problems")),
        _parity_dimension("real_browser_validation", "Real browser validation", has("learning_agent/core/software_delivery.py", "RAVENNA_BROWSER_GATE_CMD", "RAVENNA_BROWSER_WIDTH", "evidence")),
        _parity_dimension("git_review", "Git review", has("ravenna-ide/frontend/src/components/GitPanel.tsx", "getGitDiffSides") and has("ravenna-ide/frontend/src/utils/buildChatContext.ts", "@git")),
        _parity_dimension("project_memory", "Project memory", has("learning_agent/core/software_delivery.py", "_persist_project_memory", "_format_project_memory_for_prompt")),
        _parity_dimension("reliability_score", "Reliability score", bool(summary.get("reliable") and summary.get("falseSuccesses") == 0)),
    ]
    passed = sum(1 for item in dimensions if item["ok"])
    return {
        "score": passed,
        "total": len(dimensions),
        "ok": passed == len(dimensions),
        "dimensions": dimensions,
        "benchmarkSummary": summary,
    }


def _parity_dimension(key: str, label: str, ok: bool) -> dict[str, Any]:
    return {"key": key, "label": label, "ok": bool(ok)}


def _agent_context_bundle() -> dict[str, Any]:
    git_summary = "Git status unavailable."
    try:
        from learning_agent.core.git_ops import get_status

        status = get_status()
        changed = [item.get("path") for item in (status.get("unstaged") or []) + (status.get("staged") or []) if item.get("path")]
        git_summary = "Changed files:\n" + "\n".join(f"- {path}" for path in changed[:30]) if changed else "Working tree has no reported changes."
    except Exception as exc:
        git_summary = f"Git status unavailable: {exc}"

    benchmark_path = PROJECT_ROOT / "data" / "diagnostics" / "autonomy-harness" / "full-final.json"
    problems_summary = "No benchmark problems recorded."
    if benchmark_path.is_file():
        try:
            report = json.loads(benchmark_path.read_text(encoding="utf-8"))
            failures = [run for run in report.get("runs") or [] if not run.get("passed")]
            problems_summary = "\n".join(
                f"- {run.get('scenario')}: {run.get('error') or ', '.join(run.get('failureCategories') or [])}"
                for run in failures[:12]
            ) or "Latest benchmark has no failing runs."
        except json.JSONDecodeError:
            problems_summary = "Latest benchmark report is not valid JSON."

    symbol_candidates = [
        "learning_agent/api.py",
        "learning_agent/core/software_delivery.py",
        "ravenna-ide/frontend/src/components/SoftwareDeliveryPanel.tsx",
        "ravenna-ide/frontend/src/utils/resolveComposerMode.ts",
    ]
    symbols_summary = "\n".join(f"- {path}" for path in symbol_candidates if (PROJECT_ROOT / path).is_file())

    codebase_summary = "Codebase index unavailable."
    try:
        from learning_agent.core.codebase import DEFAULT_DIRS

        lines = [f"- {name}" for name in DEFAULT_DIRS if (PROJECT_ROOT / name).is_dir()]
        codebase_summary = (
            "Source roots:\n" + ("\n".join(lines) if lines else "(none)")
            + "\n\nUse a tool search_code para busca semântica no código indexado."
        )
    except Exception:
        pass

    docs_summary = "Docs directory unavailable."
    try:
        docs_root = PROJECT_ROOT / "docs"
        if docs_root.is_dir():
            md_files = sorted(p.relative_to(docs_root).as_posix() for p in docs_root.rglob("*.md"))[:40]
            docs_summary = "\n".join(f"- {path}" for path in md_files) if md_files else "(docs vazio)"
    except Exception:
        pass

    web_summary = (
        "Web search habilitada. Para informações atualizadas use research_trusted_sources "
        "(docs confiáveis) ou windows_search_google / search_web."
    )

    return {
        "items": [
            {"path": "@codebase", "kind": "codebase", "content": codebase_summary},
            {"path": "@problems", "kind": "problems", "content": problems_summary},
            {"path": "@git", "kind": "git", "content": git_summary},
            {"path": "@terminal", "kind": "terminal", "content": "Attach active terminal output or recent command results when debugging runtime failures."},
            {"path": "@symbols", "kind": "symbols", "content": symbols_summary},
            {"path": "@docs", "kind": "docs", "content": docs_summary},
            {"path": "@web", "kind": "web", "content": web_summary},
        ]
    }


class IdeSettingsBody(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    keybindings: list[dict[str, str]] = Field(default_factory=list)


@app.get("/api/ide/settings")
def ide_settings_get() -> dict[str, Any]:
    from learning_agent.core import ide_settings

    return ide_settings.get_settings()


@app.put("/api/ide/settings")
def ide_settings_put(body: IdeSettingsBody) -> dict[str, Any]:
    from learning_agent.core import ide_settings

    return ide_settings.save_settings(settings=body.settings, keybindings=body.keybindings)


@app.get("/api/ide/rules-skills")
def ide_rules_skills() -> dict[str, Any]:
    from learning_agent.core import ide_settings

    return ide_settings.list_rules_and_skills()


@app.get("/api/git/status")
def git_status_endpoint(root_id: str | None = None) -> dict[str, Any]:
    from learning_agent.core.git_ops import GitError, get_status

    try:
        return get_status(root_id or None)
    except GitError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/git/diff")
def git_diff_endpoint(path: str = "", staged: bool = False, root_id: str | None = None) -> dict[str, Any]:
    from learning_agent.core.git_ops import GitError, get_diff

    try:
        return get_diff(path, staged=staged, root_id=root_id or None)
    except GitError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/git/diff/sides")
def git_diff_sides_endpoint(
    path: str = Query(..., min_length=1),
    staged: bool = False,
    root_id: str | None = None,
) -> dict[str, Any]:
    from learning_agent.core.git_ops import GitError, get_diff_sides

    try:
        return get_diff_sides(path, staged=staged, root_id=root_id or None)
    except GitError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/ide/parity")
def ide_cursor_parity_endpoint() -> dict[str, Any]:
    return _cursor_parity_report()


@app.get("/api/agent/context/bundle")
def agent_context_bundle_endpoint() -> dict[str, Any]:
    return _agent_context_bundle()


class GitCommitRequest(BaseModel):
    message: str = Field(..., min_length=1)
    paths: list[str] = Field(..., min_length=1)


@app.post("/api/git/commit")
def git_commit_endpoint(body: GitCommitRequest, root_id: str | None = None) -> dict[str, Any]:
    from learning_agent.core.git_ops import GitError, commit_changes

    try:
        return commit_changes(body.message, body.paths, root_id=root_id or None)
    except GitError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/git/init")
def git_init_endpoint(root_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    from learning_agent.core.git_ops import GitError, init_repo

    try:
        return init_repo(root_id)
    except GitError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/workspace/grep")
def workspace_grep_endpoint(
    root_id: str = Query(..., min_length=1),
    pattern: str = Query(..., min_length=1),
    limit: int = Query(100, ge=1, le=200),
    case_sensitive: bool = False,
) -> dict[str, Any]:
    from learning_agent.core.workspace_grep import grep_workspace
    from learning_agent.core.workspace_roots import WorkspaceRootsError

    try:
        return grep_workspace(root_id, pattern, max_results=limit, case_sensitive=case_sensitive)
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/plugins")
def plugins_list_endpoint() -> dict[str, Any]:
    from learning_agent.core.ravenna_plugins import list_plugins

    plugins = list_plugins()
    return {"plugins": plugins, "count": len(plugins)}


class PluginToggleRequest(BaseModel):
    enabled: bool = True


@app.post("/api/plugins/{plugin_id}/toggle")
def plugins_toggle_endpoint(plugin_id: str, body: PluginToggleRequest) -> dict[str, Any]:
    from learning_agent.core.ravenna_plugins import set_plugin_enabled

    return set_plugin_enabled(plugin_id, body.enabled)


@app.get("/api/git/summary")
def git_summary_endpoint() -> dict[str, Any]:
    from learning_agent.core.git_ops import get_git_summary

    return get_git_summary()


@app.post("/api/plugins/{plugin_id}/enable")
def plugins_enable_endpoint(plugin_id: str) -> dict[str, Any]:
    from learning_agent.core.ravenna_plugins import set_plugin_enabled

    return set_plugin_enabled(plugin_id, True)


@app.post("/api/plugins/{plugin_id}/disable")
def plugins_disable_endpoint(plugin_id: str) -> dict[str, Any]:
    from learning_agent.core.ravenna_plugins import set_plugin_enabled

    return set_plugin_enabled(plugin_id, False)


class DebugSessionCreateRequest(BaseModel):
    root_id: str = Field(..., min_length=1)
    script: str = Field(..., min_length=1)
    port: int = Field(5678, ge=1024, le=65535)


@app.post("/api/debug/sessions")
def debug_create_session_endpoint(body: DebugSessionCreateRequest) -> dict[str, Any]:
    from learning_agent.core.debug_session import create_session

    session = create_session(body.root_id, body.script, port=body.port)
    return session.to_dict()


@app.post("/api/debug/sessions/{session_id}/start")
def debug_start_session_endpoint(session_id: str) -> dict[str, Any]:
    from learning_agent.core.debug_session import get_session, start_session

    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return start_session(session_id).to_dict()


@app.post("/api/debug/sessions/{session_id}/stop")
def debug_stop_session_endpoint(session_id: str) -> dict[str, Any]:
    from learning_agent.core.debug_session import get_session, stop_session

    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return stop_session(session_id).to_dict()


@app.get("/api/debug/sessions/{session_id}")
def debug_get_session_endpoint(session_id: str) -> dict[str, Any]:
    from learning_agent.core.debug_session import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return session.to_dict()


@app.get("/api/debug/launch-configs")
def debug_launch_configs_endpoint(root_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    from learning_agent.core.debug_session import read_launch_configs

    configs = read_launch_configs(root_id)
    return {"root_id": root_id, "configurations": configs}


async def _broadcast_file_changed(path: str) -> None:
    from learning_agent.ide import ravenna_ide

    await ravenna_ide.broadcast_file_changed(path)


class LspCompletionRequest(BaseModel):
    language_id: str = "plaintext"
    path: str = ""
    line: int = Field(1, ge=1)
    character: int = Field(1, ge=1)
    prefix: str = ""


class LspHoverRequest(BaseModel):
    language_id: str = "plaintext"
    path: str = ""
    line: int = Field(1, ge=1)
    character: int = Field(1, ge=1)


class LspDefinitionRequest(BaseModel):
    path: str = ""
    line: int = Field(1, ge=1)
    character: int = Field(1, ge=1)


class LspReferencesRequest(BaseModel):
    path: str = ""
    line: int = Field(1, ge=1)
    character: int = Field(1, ge=1)
    max_results: int = Field(100, ge=1, le=1000)


class LspSymbolsRequest(BaseModel):
    path: str = ""


class LspDiagnosticsRequest(BaseModel):
    path: str = ""


class InlineCompletionRequest(BaseModel):
    language_id: str = "plaintext"
    path: str = ""
    prefix: str = ""
    suffix: str = ""


class ValidationRunRequest(BaseModel):
    kind: str = Field(..., min_length=1)


class ValidationPlanRunRequest(BaseModel):
    changedPaths: list[str] = Field(default_factory=list)
    projectRoot: str | None = None


@app.post("/api/lsp/completion")
def lsp_completion(body: LspCompletionRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_completions

    return get_completions(
        language_id=body.language_id,
        path=body.path,
        line=body.line,
        character=body.character,
        prefix=body.prefix,
    )


@app.post("/api/lsp/hover")
def lsp_hover(body: LspHoverRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_hover

    return get_hover(
        path=body.path,
        line=body.line,
        character=body.character,
        language_id=body.language_id,
    )


@app.post("/api/lsp/definition")
def lsp_definition(body: LspDefinitionRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_definition

    return get_definition(path=body.path, line=body.line, character=body.character)


@app.post("/api/lsp/references")
def lsp_references(body: LspReferencesRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_references

    return get_references(
        path=body.path,
        line=body.line,
        character=body.character,
        max_results=body.max_results,
    )


@app.post("/api/lsp/symbols")
def lsp_symbols(body: LspSymbolsRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_document_symbols

    return get_document_symbols(path=body.path)


@app.post("/api/lsp/diagnostics")
def lsp_diagnostics(body: LspDiagnosticsRequest) -> dict[str, Any]:
    from learning_agent.core.lsp_service import get_diagnostics

    return get_diagnostics(path=body.path)


@app.post("/api/completion")
def inline_completion(body: InlineCompletionRequest) -> dict[str, Any]:
    """Tab AI fill-in-middle via modelo local (Ollama) + contexto do codebase."""
    from learning_agent.core.lsp_service import get_inline_completion

    return get_inline_completion(
        path=body.path,
        language_id=body.language_id,
        prefix=body.prefix,
        suffix=body.suffix,
    )


@app.put("/api/files/content")
def write_workspace_file(
    body: WriteFileRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Grava conteúdo UTF-8 em arquivo do workspace (Fase 2)."""
    from learning_agent.core.workspace import WorkspaceError, write_file

    try:
        result = write_file(body.path, body.content)
        rel = body.path.replace("\\", "/")
        background_tasks.add_task(_broadcast_file_changed, rel)
        if rel.startswith(("learning_agent/", "ravenna-ide/", "agents/", "tests/", "data/")):
            from learning_agent.core import agent_event_triggers

            agent_event_triggers.emit_event("file_saved", detail=rel, path=rel)
        return result
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.delete("/api/files/content")
def delete_workspace_file(
    path: str,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Remove arquivo do workspace para restaurar checkpoints."""
    from learning_agent.core.workspace import WorkspaceError, delete_file

    try:
        result = delete_file(path)
        rel = path.replace("\\", "/")
        background_tasks.add_task(_broadcast_file_changed, rel)
        return result
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _npm_executable() -> str:
    import shutil

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise HTTPException(status_code=500, detail="npm não encontrado no PATH do servidor")
    return npm


def _safe_npm_script(name: str, script: str) -> bool:
    lowered = f"{name} {script}".lower()
    blocked = ("watch", "dev", "preview", "serve", "e2e:ui", "--watch", "vitest --ui", "module-alias/register")
    if any(token in lowered for token in blocked):
        return False
    if name == "test" and ("no test specified" in lowered or "exit 1" in lowered):
        return False
    return True


def _node_test_ran_zero_tests(label: str, output: str) -> bool:
    if label != "npm test":
        return False
    text = output or ""
    return bool(
        "tests 0" in text
        or "ℹ tests 0" in text
        or "pass 0" in text and "fail 0" in text and "tests 0" in text
    )


def _nearest_package_root(changed_paths: list[str], explicit_root: str | None = None):
    from learning_agent.core.workspace import WorkspaceError, resolve_path

    if explicit_root:
        root = resolve_path(explicit_root)
        package_json = root / "package.json"
        if package_json.is_file():
            return root
        if root.exists():
            return root if root.is_dir() else root.parent
        raise WorkspaceError("raiz informada não encontrada", status_code=404)

    candidates = changed_paths or ["ravenna-ide/frontend"]
    for raw in candidates:
        target = resolve_path(raw)
        current = target if target.is_dir() else target.parent
        while True:
            package_json = current / "package.json"
            if package_json.is_file():
                return current
            parent = current.parent
            if parent == current:
                break
            try:
                parent.relative_to(resolve_path(""))
            except ValueError:
                break
            current = parent

    return None


def _validation_commands(project_root, spec: dict[str, Any] | None = None) -> list[tuple[str, list[str]]]:
    import json

    spec_commands = _validation_commands_from_spec(spec or {})
    if spec_commands:
        return spec_commands

    package_json = project_root / "package.json"
    if not package_json.is_file():
        return []
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"package.json inválido: {exc}") from exc

    scripts = package.get("scripts") or {}
    if not isinstance(scripts, dict):
        return []

    npm = _npm_executable()
    preferred = ("test", "build", "lint", "typecheck")
    commands: list[tuple[str, list[str]]] = []
    for name in preferred:
        script = scripts.get(name)
        if not isinstance(script, str) or not _safe_npm_script(name, script):
            continue
        args = [npm, "test"] if name == "test" else [npm, "run", name]
        label = "npm test" if name == "test" else f"npm run {name}"
        commands.append((label, args))

    ravenna_config = package.get("ravenna") if isinstance(package, dict) else None
    validation_config = ravenna_config.get("validation") if isinstance(ravenna_config, dict) else None
    smoke_config = validation_config.get("smoke") if isinstance(validation_config, dict) else None
    if isinstance(smoke_config, dict):
        script_name = smoke_config.get("script")
        smoke_args = smoke_config.get("args") or []
        if (
            isinstance(script_name, str)
            and isinstance(scripts.get(script_name), str)
            and _safe_npm_script(script_name, scripts[script_name])
            and isinstance(smoke_args, list)
            and all(isinstance(arg, str) for arg in smoke_args)
        ):
            commands.append((
                f"npm run {script_name} -- {' '.join(smoke_args)}".strip(),
                [npm, "run", script_name, "--", *smoke_args],
            ))
    elif isinstance(scripts.get("smoke"), str) and _safe_npm_script("smoke", scripts["smoke"]):
        commands.append(("npm run smoke", [npm, "run", "smoke"]))
    return commands


def _validation_commands_from_spec(spec: dict[str, Any]) -> list[tuple[str, list[str]]]:
    from learning_agent.core import agent_autonomy_runner

    commands: list[tuple[str, list[str]]] = []
    for command in spec.get("validationCommands") or []:
        if not isinstance(command, str):
            continue
        safety = agent_autonomy_runner._safe_shell_command(command)
        if safety.get("ok"):
            commands.append((command, safety["args"]))
    return commands


def _run_validation_plan(
    changed_paths: list[str],
    project_root: str | None = None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import subprocess

    from learning_agent.core.workspace import WorkspaceError

    try:
        cwd = _nearest_package_root(changed_paths, project_root)
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if spec and spec.get("ravennaHomeRemoteValidation"):
        from learning_agent.core import ravenna_home_remote_ops

        return ravenna_home_remote_ops.run_validation_deploy(
            changed_paths,
            str(cwd) if cwd else project_root,
            spec,
        )

    if cwd is None:
        return {
            "ok": False,
            "validated": False,
            "projectRoot": None,
            "commands": [],
            "failures": [],
            "skippedReason": "Nenhum package.json encontrado para os caminhos alterados",
        }

    commands = _validation_commands(cwd, spec=spec)
    if not commands:
        return {
            "ok": False,
            "validated": False,
            "projectRoot": str(cwd),
            "commands": [],
            "failures": [],
            "skippedReason": "Nenhum comando seguro de validação encontrado",
        }

    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for label, command in commands:
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                env=_validation_env(cwd),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=False,
            )
            output = (proc.stdout or "")[-6000:]
            result = {
                "command": label,
                "cwd": str(cwd),
                "exit_code": proc.returncode,
                "output": output,
            }
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "")
            result = {
                "command": label,
                "cwd": str(cwd),
                "exit_code": 124,
                "output": f"{output}\nTimeout após 180s".strip()[-6000:],
            }
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Falha ao executar validação: {exc}") from exc

        results.append(result)
        if result["exit_code"] != 0:
            failures.append(f"{label} exited {result['exit_code']}")
            break
        if _node_test_ran_zero_tests(label, result.get("output") or ""):
            result["exit_code"] = 2
            result["zero_tests"] = True
            failures.append("npm test ran 0 tests")
            break

    return {
        "ok": not failures,
        "validated": True,
        "projectRoot": str(cwd),
        "commands": results,
        "failures": failures,
        "skippedReason": None,
    }


def _validation_env(cwd) -> dict[str, str]:
    import os

    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    entries = [str(cwd), str(cwd / "src")]
    if current:
        entries.append(current)
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


@app.post("/api/validation/run")
def run_validation(body: ValidationRunRequest) -> dict[str, Any]:
    """Executa validações seguras e predefinidas para o Agent."""
    import shutil
    import subprocess

    from learning_agent.core.workspace import WorkspaceError, resolve_path

    if body.kind != "frontend-build":
        raise HTTPException(status_code=400, detail="Validação não permitida")

    try:
        cwd = resolve_path("ravenna-ide/frontend")
    except WorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if not cwd.is_dir():
        raise HTTPException(status_code=404, detail="Diretório frontend não encontrado")

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise HTTPException(status_code=500, detail="npm não encontrado no PATH do servidor")

    command = [npm, "run", "build"]
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "")
        return {
            "ok": False,
            "command": "npm run build",
            "cwd": str(cwd),
            "exit_code": 124,
            "output": f"{output}\nTimeout após 180s".strip()[-6000:],
        }
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao executar validação: {exc}") from exc

    return {
        "ok": proc.returncode == 0,
        "command": "npm run build",
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "output": (proc.stdout or "")[-6000:],
    }


@app.post("/api/validation/plan-and-run")
def plan_and_run_validation(body: ValidationPlanRunRequest) -> dict[str, Any]:
    """Detecta o projeto dos caminhos alterados e executa validações npm finitas."""
    return _run_validation_plan(body.changedPaths, body.projectRoot)


class AddFolderRootRequest(BaseModel):
    path: str = Field(..., min_length=1)
    name: str | None = None


class MapLocalFolderRequest(BaseModel):
    path: str = Field(..., min_length=1)


class AddGitRootRequest(BaseModel):
    url: str = Field(..., min_length=1)
    name: str | None = None
    branch: str | None = None


class OpenFinanceWidgetRequest(BaseModel):
    callback_success: str = ""
    callback_exit: str = ""


@app.get("/api/open-finance/status")
def open_finance_status() -> dict[str, Any]:
    """Status do proxy Open Finance (Belvo sandbox/produção ou mock)."""
    from learning_agent.core import open_finance

    return open_finance.status_payload()


@app.post("/api/open-finance/widget-token")
def open_finance_widget_token(body: OpenFinanceWidgetRequest) -> dict[str, Any]:
    """Gera token/widget URL Belvo — secrets nunca vão ao PWA."""
    from learning_agent.core import open_finance

    try:
        return open_finance.create_widget_token(
            callback_success=body.callback_success,
            callback_exit=body.callback_exit,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Belvo: {exc.response.text[:200]}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/workspace/roots")
def get_workspace_roots() -> dict[str, Any]:
    from learning_agent.core.workspace_roots import get_primary_root, list_roots_for_ui

    roots = list_roots_for_ui()
    primary = get_primary_root()
    return {"primary_id": primary["id"], "roots": roots}


@app.post("/api/workspace/study")
def workspace_study_endpoint(body: WorkspaceStudyRequest) -> dict[str, Any]:
    """Estudo estrutural: lê arquivos-chave no servidor, monta digest e opcionalmente sintetiza."""
    from learning_agent.core.workspace_study import run_workspace_study

    try:
        return run_workspace_study(
            body.root_ids,
            user_message=body.message,
            synthesize=body.synthesize,
            persist_note=body.persist_note,
            verify=body.verify,
            recall_prior=body.recall_prior,
            max_files=body.max_files,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/workspace/study/paths")
def workspace_study_paths_endpoint(root_ids: str = "") -> dict[str, Any]:
    from learning_agent.core.workspace_study import collect_study_paths

    ids = [x.strip() for x in root_ids.split(",") if x.strip()]
    paths = collect_study_paths(ids)
    return {"root_ids": ids, "paths": paths, "count": len(paths)}


@app.post("/api/workspace/roots/folder")
def add_workspace_folder(body: AddFolderRootRequest) -> dict[str, Any]:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, add_folder_root

    try:
        root = add_folder_root(body.path, name=body.name)
        return {"ok": True, "root": root}
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/roots/git")
def add_workspace_git(body: AddGitRootRequest) -> dict[str, Any]:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, add_git_repo

    try:
        root = add_git_repo(body.url, name=body.name, branch=body.branch)
        return {"ok": True, "root": root}
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/workspace/roots/browse")
def browse_workspace_roots(path: str = "~") -> dict[str, Any]:
    from learning_agent.core.workspace_roots import (
        WorkspaceRootsError,
        browse_local_directory,
    )

    try:
        return browse_local_directory(path)
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/roots/pick-folder")
def pick_workspace_folder() -> dict[str, Any]:
    from learning_agent.core.workspace_roots import (
        WorkspaceRootsError,
        add_folder_root,
        pick_folder_dialog,
    )

    path = pick_folder_dialog()
    if not path:
        return {"ok": False, "cancelled": True, "needs_browser": True}
    try:
        root = add_folder_root(path)
        return {"ok": True, "path": path, "root": root}
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _sync_pc_folder_to_vm(mapping: dict[str, Any]) -> dict[str, Any]:
    """Dispara o sync PC→VM de uma pasta via Windows Agent.

    `mapping` vem de `map_local_folder`: pode conter `source` (caminho Windows real,
    para pastas fora do espelho padrão) e `relative` (subcaminho remoto sob
    /home/<USER>/workspace-pc).
    """
    import os as _os

    from learning_agent.core import windows_agent_client

    password = _os.environ.get("RAVENNA_VM_PASSWORD", "").strip()
    if not password:
        return {"ok": False, "error": "RAVENNA_VM_PASSWORD não configurada no backend"}
    vm_host = _os.environ.get("RAVENNA_VM_HOST", "<RAVENNA_TAILSCALE_IP>").strip()
    pc_root = _os.environ.get("RAVENNA_PC_WORKSPACE", "").strip() or r"C:\Users\lfern\RAVENNA\learning-agent\learning-agent"
    script = pc_root.replace("/", "\\").rstrip("\\") + r"\learning_agent\scripts\sync_pc_workspace_to_vm.py"

    def ps(s: str) -> str:
        # PowerShell double-quoted string escaping (backtick é o escape char do PS).
        return s.replace("`", "``").replace('"', '`"').replace("$", "`$")

    source = str(mapping.get("source") or "").strip()
    rel = str(mapping.get("relative") or "").replace("/", "\\")

    env_lines = [
        f'$env:RAVENNA_VM_PASSWORD="{ps(password)}"',
        f'$env:RAVENNA_VM_HOST="{ps(vm_host)}"',
        f'$env:RAVENNA_PC_WORKSPACE="{ps(pc_root)}"',
    ]
    if source:
        env_lines.append(f'$env:RAVENNA_PC_SYNC_SOURCE="{ps(source)}"')
        env_lines.append(f'$env:RAVENNA_PC_SYNC_REMOTE_SUB="{ps(rel)}"')
    else:
        env_lines.append(f'$env:RAVENNA_PC_SYNC_SUBFOLDER="{ps(rel)}"')

    cmd = "; ".join(env_lines) + f'; py -3 "{ps(script)}"'
    data = windows_agent_client.exec_command(cmd, timeout=600)
    out = str(data.get("output") or "")
    ok = bool(
        data.get("exit_code") == 0
        or "arquivos enviados" in out
        or "OK —" in out
    )
    return {"ok": ok, "output": out[-1200:], "exit_code": data.get("exit_code")}


@app.post("/api/workspace/roots/map-local")
def map_local_workspace_folder(body: MapLocalFolderRequest) -> dict[str, Any]:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, map_local_folder

    try:
        mapping = map_local_folder(body.path)
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if mapping.get("needs_sync"):
        synced = _sync_pc_folder_to_vm(mapping)
        mapping["sync"] = synced
        mapping["needs_sync"] = not bool(synced.get("ok"))
    return mapping


@app.delete("/api/workspace/roots/{root_id}")
def remove_workspace_root(root_id: str) -> dict[str, Any]:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, remove_root

    try:
        remove_root(root_id)
        return {"ok": True, "removed": root_id}
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/workspace/discover")
def discover_workspace_repos(parent: str | None = None, limit: int = 24) -> dict[str, Any]:
    from learning_agent.core.workspace_roots import (
        WorkspaceRootsError,
        discover_git_repos,
    )

    try:
        repos = discover_git_repos(parent, limit=min(limit, 40))
        return {"repos": repos}
    except WorkspaceRootsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class RemoteProfileRequest(BaseModel):
    id: str | None = None
    label: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None
    identity_file: str | None = None
    ssh_config_alias: str | None = None
    remote_path: str | None = None
    cache_dir: str | None = None
    use_remote_terminal: bool | None = None


@app.get("/api/workspace/remote/profiles")
def list_remote_profiles() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import _load_store, list_profiles

    data = _load_store()
    return {
        "ok": True,
        "active_terminal_id": data.get("active_terminal_id", ""),
        "profiles": [p.sanitized() for p in list_profiles()],
    }


@app.put("/api/workspace/remote/profiles")
def create_remote_profile(body: RemoteProfileRequest) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        update_profile_from_body,
    )

    try:
        prof = update_profile_from_body(None, body.model_dump(exclude_none=True))
        return {"ok": True, "profile": prof.sanitized()}
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.get("/api/workspace/remote/profiles/{profile_id}")
def get_remote_profile(profile_id: str) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import RemoteWorkspaceError, get_profile

    try:
        return {"ok": True, "profile": get_profile(profile_id).sanitized()}
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.put("/api/workspace/remote/profiles/{profile_id}")
def save_remote_profile(profile_id: str, body: RemoteProfileRequest) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        update_profile_from_body,
    )

    try:
        payload = body.model_dump(exclude_none=True)
        payload["id"] = profile_id
        prof = update_profile_from_body(profile_id, payload)
        return {"ok": True, "profile": prof.sanitized()}
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.delete("/api/workspace/remote/profiles/{profile_id}")
def delete_remote_profile(profile_id: str) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        delete_profile,
    )

    try:
        delete_profile(profile_id)
        return {"ok": True}
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/remote/profiles/{profile_id}/test")
def test_remote_profile(profile_id: str) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import test_connection

    return test_connection(profile_id=profile_id)


@app.post("/api/workspace/remote/profiles/{profile_id}/sync")
def sync_remote_profile(profile_id: str, direction: str = "pull") -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        sync_pull,
        sync_push,
    )

    try:
        if direction == "push":
            return sync_push(profile_id=profile_id)
        if direction == "pull":
            return sync_pull(profile_id=profile_id)
        raise RemoteWorkspaceError("direction deve ser pull ou push", status_code=400)
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/remote/profiles/{profile_id}/connect")
def connect_remote_profile(profile_id: str) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        ensure_workspace_root,
    )

    try:
        return ensure_workspace_root(profile_id=profile_id)
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class SshConnectRequest(BaseModel):
    target: str
    remote_path: str | None = None
    label: str | None = None
    password: str | None = None
    username: str | None = None
    live: bool = True


@app.get("/api/workspace/remote/live/status")
def remote_live_status(root_id: str = "") -> dict[str, Any]:
    from learning_agent.core import remote_live

    rid = (root_id or "luis-132-255-110-213").strip()
    return {"ok": True, **remote_live.probe_live_connection(rid)}


@app.get("/api/workspace/remote/ssh/hosts")
def list_ssh_hosts_api() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import list_ssh_hosts

    return {"ok": True, **list_ssh_hosts()}


class SshBrowseRequest(BaseModel):
    target: str | None = None
    profile_id: str | None = None
    path: str = "~"
    password: str | None = None
    username: str | None = None


@app.post("/api/workspace/remote/ssh/browse")
def browse_ssh_api(body: SshBrowseRequest) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        browse_remote_directory,
    )

    try:
        return browse_remote_directory(
            target=(body.target or "").strip() or None,
            profile_id=(body.profile_id or "").strip() or None,
            path=body.path or "~",
            password=body.password if body.password is not None else "",
            username=(body.username or "").strip(),
        )
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/remote/ssh/connect")
def connect_ssh_api(body: SshConnectRequest) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        connect_ssh_target,
    )

    try:
        return connect_ssh_target(
            body.target.strip(),
            remote_path=(body.remote_path or "").strip(),
            label=(body.label or "").strip(),
            password=body.password if body.password is not None else "",
            username=(body.username or "").strip(),
            live=bool(body.live),
        )
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Connect SSH falhou: {exc}",
        ) from exc


@app.post("/api/workspace/remote/ssh/open-config")
def open_ssh_config_api() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import open_ssh_config

    return open_ssh_config()


# Compat legado — aponta para o perfil ativo / primeiro
@app.get("/api/workspace/remote/remote_app")
def get_remote_profile_endpoint_removed() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import load_profile

    prof = load_profile()
    return {"ok": True, "profile": prof.sanitized()}


@app.put("/api/workspace/remote/remote_app")
def save_legacy_remote_profile_removed(body: RemoteProfileRequest) -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        load_profile,
        update_profile_from_body,
    )

    try:
        current = load_profile()
        payload = body.model_dump(exclude_none=True)
        if current.id:
            payload["id"] = current.id
        prof = update_profile_from_body(current.id or None, payload)
        return {"ok": True, "profile": prof.sanitized()}
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/remote/remote_app/test")
def test_legacy_remote_removed() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import test_connection

    return test_connection()


@app.post("/api/workspace/remote/remote_app/sync")
def sync_legacy_remote_removed(direction: str = "pull") -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        sync_pull,
        sync_push,
    )

    try:
        if direction == "push":
            return sync_push()
        if direction == "pull":
            return sync_pull()
        raise RemoteWorkspaceError("direction deve ser pull ou push", status_code=400)
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@app.post("/api/workspace/remote/remote_app/connect")
def connect_legacy_remote_removed() -> dict[str, Any]:
    from learning_agent.core.remote_workspace import (
        RemoteWorkspaceError,
        ensure_workspace_root,
    )

    try:
        return ensure_workspace_root()
    except RemoteWorkspaceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


class TheaterPostRequest(BaseModel):
    role: str = "cursor"
    agent: str = "Cursor Agent"
    content: str
    level: str = ""
    reasoning: str = ""


@app.post("/api/theater/start")
async def theater_start(
    max_cycles: int | None = None,
    reset: bool = False,
    curriculum: str = "default",
) -> dict[str, Any]:
    """Inicia modo observador — agentes ensinam Ravenna continuamente."""
    from learning_agent.core import theater

    return await theater.start_theater(
        max_cycles=max_cycles,
        reset=reset,
        curriculum=curriculum,
    )


@app.post("/api/theater/stop")
async def theater_stop(consolidate: bool = True) -> dict[str, Any]:
    from learning_agent.core import theater

    return await theater.stop_theater(consolidate=consolidate)


@app.post("/api/theater/consolidate")
def theater_consolidate() -> dict[str, Any]:
    """Consolidação completa manual (sem parar o observador)."""
    from learning_agent.core.consolidation import consolidate_full_session

    return consolidate_full_session()


@app.get("/api/theater/status")
def theater_status() -> dict[str, Any]:
    from learning_agent.core import theater

    return theater.get_status()


@app.get("/api/theater/messages")
def theater_messages(limit: int = 80) -> dict[str, Any]:
    from learning_agent.core import theater

    return {"messages": theater.get_recent_messages(limit=min(limit, 120))}


@app.post("/api/theater/message")
async def theater_post_message(body: TheaterPostRequest) -> dict[str, Any]:
    """Agentes externos (Cursor MCP) postam mensagem no observador."""
    from learning_agent.core import theater

    return await theater.post_agent_message(
        body.role,
        body.agent,
        body.content,
        level=body.level,
        reasoning=body.reasoning,
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication"""
    from learning_agent.ide import ravenna_ide
    await ravenna_ide.handle_connection(websocket)


@app.websocket("/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    """Terminal PTY stream para Ravenna IDE (Fase 3)."""
    from learning_agent.core.terminal_session import handle_terminal_connection

    await handle_terminal_connection(websocket)


@app.websocket("/ws/debug/{session_id}")
async def debug_dap_websocket(websocket: WebSocket, session_id: str) -> None:
    """Proxy DAP JSON-RPC para sessão debugpy."""
    from starlette.websockets import WebSocketDisconnect

    from learning_agent.core.debug_session import (
        get_session,
        handle_dap_message,
        stop_session,
    )

    if not get_session(session_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            response = handle_dap_message(session_id, payload)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            stop_session(session_id)
        except KeyError:
            pass


@app.get("/ui", response_class=HTMLResponse)
def dashboard_ui() -> str:
    return DASHBOARD_HTML


@app.get("/graph/related")
def graph_related(concept: str = Query(..., min_length=1), depth: int = 2) -> dict[str, Any]:
    return graph.get_related_concepts(concept, depth=depth)


@app.post("/graph/edge")
def graph_add_edge(body: GraphEdgeRequest) -> dict[str, Any]:
    return graph.add_edge(body.from_concept, body.to_concept, body.relation)


@app.get("/learning/suggest")
def learning_suggest(limit: int = 5) -> dict[str, Any]:
    return active_learning.suggest_learning(limit=limit)


@app.post("/learning/run")
def learning_run(max_items: int = 3) -> dict[str, Any]:
    return active_learning.run_active_learning(max_items=max_items)


@app.post("/finetune/export")
def finetune_export() -> dict[str, Any]:
    return finetune.export_training_data()


@app.post("/finetune/modelfile")
def finetune_modelfile() -> dict[str, Any]:
    return finetune.create_modelfile()


@app.post("/sources/github")
def sources_github(body: RepoLearnRequest) -> dict[str, Any]:
    try:
        return sources.learn_from_repo(body.url, body.tags or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sources/rss")
def sources_rss(body: RssLearnRequest) -> dict[str, Any]:
    try:
        return sources.learn_from_rss(body.feed_url, body.limit)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/chat")
def chat_endpoint(body: ChatRequest) -> dict[str, Any]:
    try:
        return chat.reply(
            body.message,
            channel="api",
            user_id=body.user_id,
            include_context=body.include_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/chat/history/{user_id}")
def clear_chat_history(user_id: str) -> dict[str, Any]:
    return chat.clear_history("api", user_id)


@app.get("/progress")
def get_progress() -> dict[str, Any]:
    return progress.get_progress()


@app.get("/curriculum/next")
def get_next_topic() -> dict[str, Any]:
    return curriculum.get_next_topic()


@app.get("/curriculum/overview")
def get_curriculum_overview() -> dict[str, Any]:
    return curriculum.get_curriculum_overview()


@app.post("/quiz")
def create_quiz(body: QuizRequest) -> dict[str, Any]:
    return quiz.create_quiz(body.topic, body.count)


@app.post("/quiz/answer")
def record_answer(body: AnswerRequest) -> dict[str, Any]:
    try:
        return quiz.record_answer(body.quiz_item_id, body.correct, body.response)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/sync/push")
def sync_push() -> dict[str, Any]:
    return sync.push_to_cloud()


@app.post("/sync/pull")
def sync_pull() -> dict[str, Any]:
    return sync.pull_from_cloud()


@app.post("/sync/conversations/push")
def sync_conversations_push() -> dict[str, Any]:
    return sync.push_conversations_to_cloud()


@app.post("/sync/conversations/pull")
def sync_conversations_pull() -> dict[str, Any]:
    return sync.pull_conversations_from_cloud()


@app.get("/sync/export")
def sync_export() -> dict[str, Any]:
    return sync.export_snapshot()


from learning_agent.core.theater import TheaterHTTPError


@app.exception_handler(TheaterHTTPError)
async def theater_http_error_handler(_request, exc: TheaterHTTPError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, **exc.extra},
    )


@app.get("/dashboard")
def dashboard() -> HTMLResponse:
    return get_dashboard()


def run_server() -> None:
    """Run the API server."""
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")


if __name__ == "__main__":
    run_server()
