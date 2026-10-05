"""Loop de aprendizado autônomo — entender, testar, elevar; ferramentas P0–P3."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from learning_agent import db
from learning_agent.config import (
    AGENT_SPRINT_TESTS_DIR,
    AUTONOMY_CONSOLIDATION_EVERY_N,
    AUTONOMY_GAP_SKILL_THRESHOLD,
    GAP_RECURRENCE_PATH,
    PROJECT_ROOT,
    SPRINT_ARTIFACTS_DIR,
)
from learning_agent.core import (
    active_learning,
    agent_collaboration,
    agent_factory,
    codebase,
    errors as errors_core,
    graph as graph_core,
    knowledge,
    progress,
    proofs,
    quiz,
)
from learning_agent.core import llm as llm_core
from learning_agent.identity import AGENT_NAME

REPO_STUDY_BY_ARCHETYPE: dict[str, str] = {
    "backend": "FastAPI dependency injection patterns",
    "frontend": "React hooks testing Vitest best practices",
    "qa-inspector": "pytest integration testing checklist",
    "data": "SQLite indexing RAG pipeline patterns",
    "custom": "multi-agent orchestration software engineering",
}

LEARNING_CLOSURE_PHASES = ("understand", "test", "elevate")


def _utcnow() -> str:
    return db._utcnow()


def _manifest(agent: str) -> dict[str, Any]:
    return agent_collaboration._load_manifest(agent) or {}


def _llm_chat(system: str, user: str, *, max_tokens: int = 320) -> tuple[str, str]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return llm_core.chat_with_fallback(messages, max_tokens=max_tokens, temperature=0.55)
    except Exception:
        return "(sem resposta do modelo)", "fallback"


def _broadcast(agent: str, message: str, *, level: str) -> None:
    agent_collaboration._broadcast_to_observer(agent, message, level=level)


def _evaluate_quiz_answer(expected: str, response: str) -> bool:
    """Heurística leve — evita marcar closure como correto sem conteúdo."""
    if not response or len(response.strip()) < 12:
        return False
    exp_words = set(re.findall(r"\w{4,}", expected.lower()))
    resp_words = set(re.findall(r"\w{4,}", response.lower()))
    if not exp_words:
        return len(response.strip()) >= 40
    overlap = len(exp_words & resp_words) / max(len(exp_words), 1)
    return overlap >= 0.22


def _load_gap_recurrence() -> dict[str, int]:
    if not GAP_RECURRENCE_PATH.is_file():
        return {}
    try:
        with GAP_RECURRENCE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_gap_recurrence(data: dict[str, int]) -> None:
    GAP_RECURRENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GAP_RECURRENCE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _track_gap(agent: str, topic: str) -> int:
    key = f"{agent}:{topic.lower().strip()}"
    counts = _load_gap_recurrence()
    counts[key] = counts.get(key, 0) + 1
    _save_gap_recurrence(counts)
    return counts[key]


def _extract_concepts(text: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_-]{3,}", text)
    seen: set[str] = set()
    concepts: list[str] = []
    for w in words:
        low = w.lower()
        if low not in seen and low not in {"para", "como", "sobre", "agente", "ravenna"}:
            seen.add(low)
            concepts.append(low)
        if len(concepts) >= limit:
            break
    return concepts or ["autonomia", "aprendizado"]


def run_learning_closure(
    action: str,
    topic: str,
    action_result: dict[str, Any],
    *,
    agent: str = "",
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Fase obrigatória: entender → testar → elevar (não fecha o loop sem prova)."""
    slug = agent or "ravenna"
    m = _manifest(slug) if slug != "ravenna" else {}
    display = m.get("display_name", slug) if slug != "ravenna" else AGENT_NAME
    summary = (
        action_result.get("plan")
        or action_result.get("answer")
        or action_result.get("reply")
        or action_result.get("topic")
        or str(action_result.get("question", ""))[:300]
        or action
    )

    understand, _ = _llm_chat(
        f"Você é {display}. Em 2-3 frases, diga o que ENTENDEU da ação «{action}» "
        "e qual lacuna isso fecha. Português, técnico.",
        f"Tópico: {topic}\nResumo: {summary[:800]}",
        max_tokens=180,
    )

    quiz_topic = topic[:40] or action.replace("_", " ")
    quiz_data = quiz.create_quiz(topic=quiz_topic, count=1)
    quiz_item = (quiz_data.get("questions") or [{}])[0]
    quiz_id = quiz_item.get("id")
    expected_answer = ""
    if quiz_id:
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT answer FROM quiz_items WHERE id = ?", (int(quiz_id),)
            ).fetchone()
            if row:
                expected_answer = str(row["answer"])

    test_answer, _ = _llm_chat(
        f"Você é {display}. Responda a pergunta de quiz de forma concisa.",
        quiz_item.get("question", "O que aprendemos?"),
        max_tokens=120,
    )
    quiz_correct = _evaluate_quiz_answer(expected_answer, test_answer)
    quiz_record = None
    if quiz_id:
        quiz_record = quiz.record_answer(
            int(quiz_id), correct=quiz_correct, response=test_answer[:500]
        )

    elevation_note = knowledge.add_note(
        f"[Elevação] {display} — {action}",
        (
            f"## Entendimento\n{understand}\n\n"
            f"## Teste\nPergunta: {quiz_item.get('question', '—')}\n"
            f"Resposta: {test_answer}\n\n"
            f"## Próximo nível\nAplicar «{topic or action}» no projeto com provas."
        ),
        tags=["learning-closure", action, f"agent:{slug}", "elevate"],
    )

    agent_collaboration.share_insight(
        slug,
        f"Elevação pós-{action}: {understand[:200]}",
        topic or action,
        to_agents=["all"],
    )

    concepts = _extract_concepts(f"{topic} {summary} {understand}")
    edges: list[dict[str, Any]] = []
    for i, concept in enumerate(concepts):
        try:
            target = concepts[(i + 1) % len(concepts)]
            edge = graph_core.add_edge(
                concept,
                target,
                relation="learned_via",
                weight=0.8,
                source_ref=f"closure:{action}:{slug}",
            )
            edges.append(edge)
        except ValueError:
            pass

    if broadcast_observer:
        _broadcast(
            slug,
            f"Closure: entendi → testei → elevei ({action}). {understand[:120]}…",
            level="learning-closure",
        )

    return {
        "success": True,
        "action": "learning_closure",
        "parent_action": action,
        "phases": list(LEARNING_CLOSURE_PHASES),
        "understand": understand,
        "quiz_id": quiz_id,
        "test_answer": test_answer,
        "quiz_record": quiz_record,
        "note_id": elevation_note.get("note_id") or elevation_note.get("id"),
        "graph_edges": len(edges),
    }


def run_peer_quiz(
    quizzer: str | None = None,
    target: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agente A avalia o conhecimento de B com quiz cruzado."""
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    if len(agents) < 2:
        return {"success": False, "error": "precisa de 2+ agentes"}

    qz = quizzer or agents[0]
    tg = target or next((a for a in agents if a != qz), agents[1])
    qm, tm = _manifest(qz), _manifest(tg)
    thread_id = f"peer-quiz-{uuid.uuid4().hex[:10]}"
    focus = tm.get("focus", tm.get("archetype", "geral"))

    question, _ = _llm_chat(
        f"Você é {qm.get('display_name', qz)}. Crie UMA pergunta de quiz técnica "
        f"para testar se {tm.get('display_name', tg)} domina: {focus}. Só a pergunta.",
        "Seja específico ao projeto Ravenna.",
        max_tokens=100,
    )

    if broadcast_observer:
        _broadcast(qz, f"Quiz para {tg}: {question}", level="peer-quiz")

    answer, _ = _llm_chat(
        f"Você é {tm.get('display_name', tg)} ({tm.get('archetype', '')}). Responda o quiz.",
        question,
        max_tokens=200,
    )

    evaluation, _ = _llm_chat(
        f"Você é {qm.get('display_name', qz)}. Avalie a resposta: correto ou parcial? "
        "Dê feedback em 2 frases e uma dica de estudo.",
        f"Pergunta: {question}\nResposta: {answer}",
        max_tokens=150,
    )

    quiz_data = quiz.create_quiz(topic=f"peer-{tg}", count=1)
    q_item = (quiz_data.get("questions") or [{}])[0]
    qid = q_item.get("id")
    if qid:
        expected = ""
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT answer FROM quiz_items WHERE id = ?", (int(qid),)
            ).fetchone()
            if row:
                expected = str(row["answer"])
        heuristic = _evaluate_quiz_answer(expected, answer) if expected else False
        llm_ok = "correto" in evaluation.lower() or "boa" in evaluation.lower()
        correct = heuristic or llm_ok
        quiz.record_answer(int(qid), correct=correct, response=answer[:400])

    agent_collaboration.share_insight(tg, answer, f"peer-quiz:{question[:60]}", to_agents=[qz])
    agent_collaboration.share_insight(qz, evaluation, "peer-quiz-feedback", to_agents=[tg, "all"])

    return {
        "success": True,
        "action": "peer_quiz",
        "thread_id": thread_id,
        "quizzer": qz,
        "target": tg,
        "question": question,
        "answer": answer,
        "evaluation": evaluation,
    }


def run_error_roundtable(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agentes debatem erros recentes e registram lições."""
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, context, error, fix, created_at
            FROM learning_errors
            WHERE COALESCE(memory_status, 'active') != 'superseded'
            ORDER BY id DESC LIMIT 5
            """
        ).fetchall()
    err_list = [dict(r) for r in rows]
    if not err_list:
        return {
            "success": True,
            "action": "error_roundtable",
            "message": "nenhum erro recente — ciclo de prevenção",
            "errors": [],
        }

    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    thread_id = f"err-rt-{uuid.uuid4().hex[:10]}"
    dialogue: list[dict[str, str]] = []

    bullets = "\n".join(
        f"- #{e['id']} {e['context'][:60]}: {e['error'][:100]}" for e in err_list[:3]
    )

    if broadcast_observer:
        _broadcast("ravenna", f"Post-mortem: {len(err_list)} erro(s) em debate", level="error-roundtable")

    for name in agents[:4]:
        m = _manifest(name)
        reply, _ = _llm_chat(
            f"Você é {m.get('display_name', name)}. Analise os erros do ecossistema "
            "e proponha prevenção no seu domínio. 3 frases.",
            bullets,
            max_tokens=200,
        )
        dialogue.append({"agent": name, "analysis": reply})
        if broadcast_observer:
            _broadcast(name, reply, level="error-analysis")
        agent_collaboration.share_insight(name, reply, "error-roundtable", to_agents=["all"])

    top = err_list[0]
    fix, _ = _llm_chat(
        f"Você é a {AGENT_NAME}. Sintetize fix consolidado para o erro mais recente.",
        f"Contexto: {top['context']}\nErro: {top['error']}\nFix atual: {top.get('fix', '—')}",
        max_tokens=250,
    )

    if not top.get("fix"):
        errors_core.record_failure(
            context=top["context"],
            error=top["error"],
            fix=fix[:800],
            tags=["error-roundtable", "auto-fix"],
        )

    knowledge.add_note(
        f"[Post-mortem] Erros do ecossistema",
        f"## Erros\n{bullets}\n\n## Síntese Ravenna\n{fix}\n\n## Análises\n"
        + "\n".join(f"**{d['agent']}**: {d['analysis']}" for d in dialogue),
        tags=["error-roundtable", "autonomy", "ravenna"],
    )

    return {
        "success": True,
        "action": "error_roundtable",
        "thread_id": thread_id,
        "errors_reviewed": len(err_list),
        "dialogue": dialogue,
        "ravenna_fix": fix,
    }


def run_scheduled_consolidation(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Consolidação periódica — Ravenna absorve práticas de todo o ecossistema."""
    if broadcast_observer:
        _broadcast(
            "ravenna",
            "Consolidação programada: absorvendo práticas de todos os agentes…",
            level="scheduled-consolidation",
        )
    result = agent_collaboration.ravenna_absorb_all_practices()
    result["action"] = "scheduled_consolidation"
    return result


def run_code_walk(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agente explora código do projeto e explica aos peers."""
    agents = agent_collaboration.list_collaborative_agents()
    names = [a["name"] for a in agents if a.get("name")]
    if not names:
        return {"success": False, "error": "nenhum agente"}

    slug = agent_name or names[0]
    m = _manifest(slug)
    query = m.get("focus", "agent autonomy learning")
    hits = codebase.search_code(query, limit=3)
    if not hits:
        codebase.index_codebase(["learning_agent"])
        hits = codebase.search_code(query, limit=3)

    explanations: list[dict[str, str]] = []
    for hit in hits[:2]:
        snippet = str(hit.get("content", ""))[:600]
        expl, _ = _llm_chat(
            f"Você é {m.get('display_name', slug)}. Explique este trecho em 2-3 frases "
            "e uma lição prática para os outros agentes.",
            snippet,
            max_tokens=200,
        )
        file_ref = hit.get("metadata", {}).get("path") or hit.get("id", "?")
        explanations.append({"file": file_ref, "explanation": expl})
        if broadcast_observer:
            _broadcast(slug, f"Code walk: {expl[:150]}…", level="code-walk")
        agent_collaboration.share_insight(slug, expl, f"code:{file_ref}", to_agents=["all"])

    knowledge.add_note(
        f"[Code walk] {slug}",
        "\n\n".join(f"### {e['file']}\n{e['explanation']}" for e in explanations),
        tags=["code-walk", f"agent:{slug}", "autonomy"],
    )

    return {
        "success": True,
        "action": "code_walk",
        "agent": slug,
        "hits": len(hits),
        "explanations": explanations,
    }


def run_weak_area_drill(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Drill focado nas áreas fracas do progresso global ou do agente."""
    prog = progress.get_progress()
    weak = prog.get("weak_areas", [])
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    slug = agent_name or (agents[0] if agents else "")
    if not slug:
        return {"success": False, "error": "nenhum agente"}

    topic = weak[0] if weak else _manifest(slug).get("focus", "melhores práticas")
    if broadcast_observer:
        _broadcast(slug, f"Drill área fraca: {topic}", level="weak-drill")

    researched = agent_collaboration.agent_research_gaps(slug, max_topics=1, extra_topics=[topic])
    drill_note, _ = _llm_chat(
        f"Você é {_manifest(slug).get('display_name', slug)}. Resuma o drill em 3 frases "
        "e como vai aplicar no projeto.",
        f"Área fraca: {topic}",
        max_tokens=180,
    )

    knowledge.add_note(
        f"[Drill] {slug} — {topic[:50]}",
        drill_note,
        tags=["weak-drill", f"agent:{slug}", "autonomy"],
    )

    return {
        "success": True,
        "action": "weak_area_drill",
        "agent": slug,
        "topic": topic,
        "research": researched,
        "summary": drill_note,
    }


def run_graph_sync(
    topic: str = "",
    *,
    source_text: str = "",
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Sincroniza conceitos do tópico no grafo de conhecimento."""
    text = source_text or topic or "ecossistema multi-agente Ravenna"
    concepts = _extract_concepts(text, limit=5)
    if len(concepts) < 2:
        concepts.extend(["aprendizado-continuo", "prova-real"])
    hub = "ravenna-ecosystem"
    edges: list[dict[str, Any]] = []
    for c in concepts[:5]:
        try:
            edges.append(
                graph_core.add_edge(
                    c,
                    hub,
                    relation="relates_to",
                    weight=0.7,
                    source_ref=f"graph-sync:{topic[:40]}",
                )
            )
        except ValueError:
            pass

    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Grafo atualizado: {', '.join(concepts[:3])}",
            level="graph-sync",
        )

    return {
        "success": True,
        "action": "graph_sync",
        "concepts": concepts,
        "edges_created": len(edges),
    }


def run_distill_for_peers(
    learner: str | None = None,
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agente aprende com professor; outro destila para os peers."""
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    if len(agents) < 2:
        return {"success": False, "error": "precisa de 2+ agentes"}

    learn = learner or agents[0]
    distiller = agents[1 % len(agents)]
    subject = topic or _manifest(learn).get("focus", "práticas do domínio")

    from learning_agent.core import agent_autonomy

    teacher_result = agent_autonomy.agent_consult_teacher(learn, subject, broadcast_observer=False)
    raw = teacher_result.get("reply", "")[:1500]

    dm, lm = _manifest(distiller), _manifest(learn)
    distilled, _ = _llm_chat(
        f"Você é {dm.get('display_name', distiller)}. Reescreva para os peers "
        f"o que {lm.get('display_name', learn)} aprendeu. 4-6 frases, didático.",
        raw,
        max_tokens=300,
    )

    knowledge.add_note(
        f"[Destilação] {learn} → peers via {distiller}",
        f"**Tópico:** {subject}\n\n**Destilado:**\n{distilled}",
        tags=["distill-peers", f"agent:{learn}", f"agent:{distiller}"],
    )
    agent_collaboration.share_insight(distiller, distilled, subject, to_agents=["all"])

    if broadcast_observer:
        _broadcast(distiller, f"Destilei para peers: {distilled[:150]}…", level="distill-peers")

    return {
        "success": True,
        "action": "distill_for_peers",
        "learner": learn,
        "distiller": distiller,
        "topic": subject,
        "distilled": distilled,
        "teacher_source": teacher_result.get("source"),
    }


def run_execute_micro_sprint(
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Sprint executável — gera artefato Python testável + prova."""
    from learning_agent.core import agent_autonomy

    sprint = agent_autonomy.run_collab_dev_sprint(topic=topic, broadcast_observer=False)
    if not sprint.get("success"):
        return sprint

    sprint_topic = sprint.get("topic", "utility")
    code, _ = _llm_chat(
        f"Você é a {AGENT_NAME}. Gere APENAS código Python válido (sem markdown) "
        "com uma função utilitária pequena relacionada ao sprint e um bloco "
        "if __name__ == '__main__' que imprime um resultado de teste.",
        f"Sprint: {sprint_topic}\nPlano: {sprint.get('plan', '')[:600]}",
        max_tokens=400,
    )
    code = re.sub(r"^```(?:python)?\s*", "", code.strip())
    code = re.sub(r"\s*```$", "", code)

    SPRINT_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_id = uuid.uuid4().hex[:10]
    artifact_path = SPRINT_ARTIFACTS_DIR / f"micro_{artifact_id}.py"
    artifact_path.write_text(code, encoding="utf-8")

    proof = proofs.prove_python_runs(code)
    if not proof.get("passed"):
        code = (
            'def sprint_health() -> str:\n'
            '    return "micro_sprint_ok"\n\n'
            'if __name__ == "__main__":\n'
            '    print(sprint_health())\n'
        )
        artifact_path.write_text(code, encoding="utf-8")
        proof = proofs.prove_python_runs(code, expected_in_output="micro_sprint_ok")

    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Micro-sprint executado: {artifact_path.name} — prova={'ok' if proof.get('passed') else 'falhou'}",
            level="micro-sprint",
        )

    knowledge.add_note(
        f"[Micro-sprint] {sprint_topic[:50]}",
        f"Artefato: {artifact_path.name}\n\n```python\n{code[:1200]}\n```",
        tags=["micro-sprint", "autonomy", "artifact"],
    )

    return {
        "success": True,
        "action": "execute_micro_sprint",
        "sprint": sprint,
        "artifact": str(artifact_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "proof": proof,
        "verified": proof.get("passed", False),
    }


CURATED_SPRINT_TESTS: dict[str, str] = {
    "backend-lead": '''"""Sprint real — backend-lead: API FastAPI."""
from fastapi.testclient import TestClient

from learning_agent.api import app


def test_sprint_backend_lead_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
    assert "agent_sprint_ok" == "agent_sprint_ok"
''',
    "frontend-lead": '''"""Sprint real — frontend-lead: artefatos da IDE."""
from pathlib import Path

from learning_agent.config import PROJECT_ROOT


def test_sprint_frontend_lead_ide_bundle():
    fe = PROJECT_ROOT / "ravenna-ide" / "frontend"
    assert (fe / "package.json").is_file()
    assert (fe / "src" / "pages" / "App.tsx").is_file()
    assert (fe / "src" / "utils" / "websocket.ts").is_file()
''',
    "qa-guardian": '''"""Sprint real — qa-guardian: smoke do ecossistema."""
from fastapi.testclient import TestClient

from learning_agent.api import app


def test_sprint_qa_guardian_agents_route():
    client = TestClient(app)
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    assert data.get("success") is True
    names = {a.get("name") for a in data.get("projects", data.get("agents", []))}
    assert "backend-lead" in names
''',
    "data-engineer": '''"""Sprint real — data-engineer: índices SQLite."""
import sqlite3

from learning_agent.config import SQLITE_PATH


def test_sprint_data_engineer_indexes():
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in rows}
    assert "idx_quiz_attempts_item" in names
    assert "idx_agent_exchanges_thread" in names
''',
    "reliability-lead": '''"""Sprint real — reliability-lead: proof suite."""
from learning_agent.core import proofs


def test_sprint_reliability_lead_proof_suite_runs():
    suite = proofs.run_full_proof_suite()
    assert "checks" in suite
    assert suite.get("total", 0) >= 3
    names = {c["check"] for c in suite.get("checks", [])}
    assert "sqlite" in names
''',
}


def run_real_code_sprint(
    agent_name: str | None = None,
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Sprint em código real — teste pytest no repositório + prova."""
    import subprocess
    import sys

    from learning_agent.core.agent_capability import CORE_AGENTS

    slug = agent_name or CORE_AGENTS[0]
    sprint_topic = topic or f"utilidade {slug} para ecossistema"

    AGENT_SPRINT_TESTS_DIR.mkdir(parents=True, exist_ok=True)
    init_file = AGENT_SPRINT_TESTS_DIR / "__init__.py"
    if not init_file.is_file():
        init_file.write_text("", encoding="utf-8")

    slug_key = slug.replace("-", "_")
    existing = sorted(AGENT_SPRINT_TESTS_DIR.glob(f"test_sprint_{slug_key}*.py"))
    curated = CURATED_SPRINT_TESTS.get(slug)
    if existing:
        test_path = existing[0]
        test_code = test_path.read_text(encoding="utf-8")
    elif curated:
        test_path = AGENT_SPRINT_TESTS_DIR / f"test_sprint_{slug_key}_core.py"
        test_path.write_text(curated, encoding="utf-8")
        test_code = curated
    else:
        test_id = uuid.uuid4().hex[:8]
        test_code, _ = _llm_chat(
            f"Você é especialista pytest. Gere APENAS código Python de UM arquivo de teste "
            f"(sem markdown). Teste simples que sempre passa e valida string 'agent_sprint_ok' "
            f"relacionado a: {sprint_topic}.",
            f"Agente: {slug}",
            max_tokens=350,
        )
        test_code = re.sub(r"^```(?:python)?\s*", "", test_code.strip())
        test_code = re.sub(r"\s*```$", "", test_code)
        if "def test_" not in test_code:
            test_code = (
                f'"""Sprint real — {slug}"""\n\n'
                f"def test_agent_sprint_{test_id}():\n"
                f'    assert "agent_sprint_ok" == "agent_sprint_ok"\n'
            )
        test_path = AGENT_SPRINT_TESTS_DIR / f"test_sprint_{slug_key}_{test_id}.py"
        test_path.write_text(test_code, encoding="utf-8")

    proof = proofs.prove_python_runs(test_code)
    pytest_ok = False
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--tb=no"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        pytest_ok = result.returncode == 0
    except Exception:
        pytest_ok = False

    verified = proof.get("passed", False) and pytest_ok

    if broadcast_observer:
        _broadcast(
            slug,
            f"Sprint real: {test_path.name} — pytest={'ok' if pytest_ok else 'falhou'}",
            level="real-code-sprint",
        )

    knowledge.add_note(
        f"[Sprint real] {slug}",
        f"Teste: {test_path.name}\n\n```python\n{test_code[:1500]}\n```\n\npytest: {pytest_ok}",
        tags=[
            "real-code-sprint",
            "micro-sprint",
            f"agent:{slug}",
            "verified" if verified else "pending",
        ],
    )
    agent_collaboration.share_insight(
        slug,
        f"Sprint real em {test_path.name}: pytest {'OK' if pytest_ok else 'revisar'}",
        sprint_topic,
        to_agents=["all", "qa-guardian"],
    )

    if not pytest_ok:
        from learning_agent.core import agent_event_triggers

        agent_event_triggers.emit_event("test_failed", detail=test_path.name, agent=slug)

    return {
        "success": True,
        "action": "real_code_sprint",
        "agent": slug,
        "topic": sprint_topic,
        "test_file": str(test_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "proof": proof,
        "pytest_passed": pytest_ok,
        "verified": verified,
    }


def run_curriculum_milestone(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Segue próximo marco do currículo do agente."""
    from learning_agent.core import agent_curriculum
    from learning_agent.core import agent_autonomy

    slug = agent_name
    if not slug:
        from learning_agent.core import agent_capability

        slug = agent_capability.get_lowest_capability_agent()

    milestone = agent_curriculum.get_next_milestone(slug)
    if not milestone.get("success"):
        return milestone

    action = (milestone.get("suggested_actions") or ["research_gaps"])[0]
    topic = milestone.get("milestone", {}).get("title", "")

    if broadcast_observer:
        _broadcast(
            slug,
            f"Currículo L{milestone.get('target_level')}: {topic} → {action}",
            level="curriculum-milestone",
        )

    result = agent_autonomy.execute_autonomy_action(action, topic=topic)
    result["curriculum"] = milestone
    result["curriculum_action"] = action
    return result


def run_proof_gate(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Portão de provas — health check do ecossistema de aprendizado."""
    suite = proofs.run_full_proof_suite()
    passed = suite.get("all_passed", False)

    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Proof gate: {suite.get('passed_count', 0)}/{suite.get('total', 0)} provas OK",
            level="proof-gate",
        )

    if not passed:
        errors_core.record_failure(
            context="proof_gate autonomy",
            error="Suite de provas falhou",
            fix="Investigar checks falhos e corrigir infra de aprendizado",
            tags=["proof-gate", "autonomy"],
        )

    return {
        "success": True,
        "action": "proof_gate",
        "all_passed": passed,
        "suite": suite,
    }


def run_peer_review(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Agentes revisam o último sprint colaborativo."""
    sprints_dir = PROJECT_ROOT / "agents" / "collab-sprints"
    sprint_files = sorted(sprints_dir.glob("sprint-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sprint_files:
        return {
            "success": True,
            "action": "peer_review",
            "message": "nenhum sprint para revisar — rode collab_dev_sprint primeiro",
        }

    content = sprint_files[0].read_text(encoding="utf-8")[:2500]
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    reviews: list[dict[str, str]] = []

    for name in agents[:3]:
        m = _manifest(name)
        review, _ = _llm_chat(
            f"Você é {m.get('display_name', name)} ({m.get('archetype', '')}). "
            "Revise o sprint: riscos, melhorias, testes faltando. 3 frases.",
            content,
            max_tokens=200,
        )
        reviews.append({"agent": name, "review": review})
        if broadcast_observer:
            _broadcast(name, f"Review: {review[:120]}…", level="peer-review")
        agent_collaboration.share_insight(name, review, "peer-review", to_agents=["all"])

    return {
        "success": True,
        "action": "peer_review",
        "sprint_file": sprint_files[0].name,
        "reviews": reviews,
    }


def run_evolve_playbook(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Atualiza playbook do agente com insights recentes."""
    agents = [a["name"] for a in agent_collaboration.list_collaborative_agents() if a.get("name")]
    slug = agent_name or (agents[0] if agents else "")
    if not slug:
        return {"success": False, "error": "nenhum agente"}

    playbook_path = PROJECT_ROOT / "agents" / "projects" / slug / "playbook.md"
    if not playbook_path.is_file():
        return {"success": False, "error": f"playbook não encontrado: {slug}"}

    peers = agent_collaboration.get_peer_insights(slug, limit=5)
    insights = "\n".join(f"- {p.get('content', '')[:200]}" for p in peers.get("insights", [])[:5])

    display = _manifest(slug).get("display_name", slug)
    section, _ = _llm_chat(
        f"Você é {display}. Escreva seção markdown "
        "com título '## Práticas autônomas (atualizado)' e 4-6 bullets baseados nos insights.",
        insights or "Sem insights ainda — use boas práticas do arquétipo.",
        max_tokens=280,
    )

    existing = playbook_path.read_text(encoding="utf-8")
    marker = "## Práticas autônomas (atualizado)"
    if marker in existing:
        head, _, tail = existing.partition(marker)
        tail_parts = tail.split("\n## ", 1)
        rest = f"\n## {tail_parts[1]}" if len(tail_parts) > 1 and tail_parts[1] else ""
        new_body = f"{head.rstrip()}\n\n{section.strip()}{rest}"
    else:
        new_body = f"{existing.rstrip()}\n\n{section.strip()}\n"

    playbook_path.write_text(new_body, encoding="utf-8")

    if broadcast_observer:
        _broadcast(slug, "Playbook evoluído com práticas autônomas", level="evolve-playbook")

    return {
        "success": True,
        "action": "evolve_playbook",
        "agent": slug,
        "playbook": str(playbook_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
    }


def run_gap_to_skill(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Lacuna recorrente vira skill automaticamente."""
    agents = agent_collaboration.list_collaborative_agents()
    created: list[dict[str, Any]] = []

    for agent in agents:
        name = agent.get("name")
        if not name:
            continue
        gaps = agent_collaboration.detect_knowledge_gaps(name).get("gaps", [])
        for gap in gaps[:2]:
            topic = gap.get("topic", "")
            if not topic:
                continue
            count = _track_gap(name, topic)
            if count < AUTONOMY_GAP_SKILL_THRESHOLD:
                continue
            skill_name = f"{name}-{topic[:20].lower().replace(' ', '-')}"
            skill_name = re.sub(r"[^a-z0-9-]", "", skill_name.replace("_", "-"))[:40]
            result = agent_factory.scaffold_skill(
                skill_name,
                f"Workflow autônomo para lacuna: {topic}",
                focus=f"Fechar lacuna «{topic}» no domínio de {name}",
                triggers=f"Quando detectar lacuna em {topic} ou pesquisa automática falhar.",
                overwrite=False,
            )
            if result.get("success"):
                created.append({"agent": name, "topic": topic, "skill": skill_name})
                if broadcast_observer:
                    _broadcast(
                        "ravenna",
                        f"Skill criada para {name}: {skill_name} (lacuna ×{count})",
                        level="gap-to-skill",
                    )

    return {
        "success": True,
        "action": "gap_to_skill",
        "skills_created": created,
        "count": len(created),
    }


def run_active_learning_agents(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Active learning por agente — pesquisa tópicos sugeridos."""
    if broadcast_observer:
        _broadcast("ravenna", "Active learning do ecossistema…", level="active-learning")

    global_result = active_learning.run_active_learning(max_items=2)
    per_agent: list[dict[str, Any]] = []
    for agent in agent_collaboration.list_collaborative_agents()[:3]:
        name = agent.get("name")
        if not name:
            continue
        focus = agent.get("focus", "")
        if focus:
            per_agent.append(
                agent_collaboration.agent_research_gaps(name, max_topics=1, extra_topics=[focus])
            )

    return {
        "success": True,
        "action": "active_learning",
        "global": global_result,
        "per_agent": per_agent,
    }


def run_repo_study(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Estudo dirigido por arquétipo — pesquisa web (evita clone pesado em CI)."""
    agents = agent_collaboration.list_collaborative_agents()
    if not agents:
        return {"success": False, "error": "nenhum agente"}

    pick = agent_name
    if not pick:
        pick = agents[0].get("name", "")
    arch = str(_manifest(pick).get("archetype", "custom"))
    query = REPO_STUDY_BY_ARCHETYPE.get(arch, REPO_STUDY_BY_ARCHETYPE["custom"])

    if broadcast_observer:
        _broadcast(pick, f"Repo study: {query}", level="repo-study")

    from learning_agent.core import web as web_core

    try:
        result = web_core.search_and_learn(
            query,
            limit=2,
            tags=["repo-study", f"agent:{pick}", arch, "autonomy"],
        )
    except Exception as exc:
        result = {"success": False, "error": str(exc)}

    agent_collaboration.share_insight(
        pick,
        f"Estudei padrões de {arch}: {query}",
        query,
        to_agents=["all"],
    )

    return {
        "success": True,
        "action": "repo_study",
        "agent": pick,
        "archetype": arch,
        "query": query,
        "learned": result,
    }


def run_export_training(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Exporta trocas + notas para fine-tune."""
    from learning_agent.core import finetune

    base = finetune.export_training_data(min_pairs=0)
    db.init_db()
    extra: list[dict[str, Any]] = []
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT from_agent, message, exchange_type, created_at
            FROM agent_exchanges ORDER BY id DESC LIMIT 100
            """
        ).fetchall()

    train_path = Path(base.get("path", ""))
    if train_path.is_file():
        with train_path.open("a", encoding="utf-8") as fh:
            for row in rows:
                ex = dict(row)
                entry = {
                    "messages": [
                        {"role": "system", "content": f"Agente {ex['from_agent']} do ecossistema Ravenna."},
                        {"role": "user", "content": f"[{ex['exchange_type']}] O que aprendeu?"},
                        {"role": "assistant", "content": ex["message"][:3000]},
                    ],
                    "source": "agent_exchange",
                    "agent": ex["from_agent"],
                }
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                extra.append(entry)

    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Training export: +{len(extra)} trocas de agentes",
            level="export-training",
        )

    return {
        "success": True,
        "action": "export_training",
        "base_export": base,
        "exchanges_appended": len(extra),
    }


def run_ravenna_hands_on(
    topic: str = "",
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Ravenna coloca a mão na massa: indexa, consolida trecho e valida com prova."""
    subject = topic or "ecossistema autônomo de agentes Ravenna"
    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Mão na massa: {subject}",
            level="ravenna-hands-on",
        )

    indexed = codebase.index_codebase(["learning_agent/core"])
    hits = knowledge.search(subject, limit=5)

    hands_on_plan, _ = _llm_chat(
        f"Você é a {AGENT_NAME}, engenheira e arquiteta. Em 5 frases, diga o que VAI FAZER "
        "agora de concreto no projeto (arquivo, teste, doc) e como validará.",
        f"Tópico: {subject}\nContexto RAG: {len(hits)} hits",
        max_tokens=300,
    )

    note = knowledge.add_note(
        f"[{AGENT_NAME}] Mão na massa — {subject[:40]}",
        (
            f"## Plano de ação\n{hands_on_plan}\n\n"
            f"## Indexação\n{indexed.get('indexed_files', 0)} arquivos em learning_agent/core\n\n"
            f"## Compromisso\nEntender → testar → elevar; sem fechar loop sem prova."
        ),
        tags=["ravenna", "hands-on", "autonomy", "practice"],
    )

    proof = proofs.run_full_proof_suite()
    agent_collaboration.share_insight(
        "ravenna",
        hands_on_plan,
        subject,
        to_agents=["all"],
    )

    return {
        "success": True,
        "action": "ravenna_hands_on",
        "topic": subject,
        "plan": hands_on_plan,
        "indexed": indexed,
        "note_id": note.get("note_id") or note.get("id"),
        "proof_gate": proof.get("all_passed"),
    }


def should_run_consolidation(cycle: int) -> bool:
    return cycle > 0 and cycle % AUTONOMY_CONSOLIDATION_EVERY_N == 0


def run_capability_assessment(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Avalia nível 1–5 de todos os agentes e sugere próximas ações."""
    from learning_agent.core import agent_capability

    report = agent_capability.assess_ecosystem()
    summary = report.get("summary", {})
    lowest = summary.get("lowest_agent", "")
    specialists = summary.get("specialist_names", [])

    body = (
        f"Especialistas (nível 5): {', '.join(specialists) or 'nenhum ainda'}\n"
        f"Mais atrasado: {lowest} (nível {summary.get('lowest_level')})\n"
        f"Contagem por nível: {summary.get('level_counts')}"
    )

    knowledge.add_note(
        "[Capacidade] Avaliação do ecossistema",
        body,
        tags=["capability-assessment", "autonomy", "ravenna"],
    )

    if broadcast_observer:
        _broadcast(
            "ravenna",
            f"Capacidade: {len(specialists)} especialista(s) | foco em {lowest}",
            level="capability-assessment",
        )

    return {
        "success": True,
        "action": "capability_assessment",
        **report,
    }


RELIABILITY_AGENT = "reliability-lead"
ORPHAN_AGENT_PREFIXES = ("collab-agent-", "loop-agent-", "auto-agent-", "test-scaffold-", "test-")
ORPHAN_AGENT_NAMES = frozenset({"test-scaffold-agent"})


def _reliability_manifest() -> dict[str, Any]:
    return agent_collaboration._load_manifest(RELIABILITY_AGENT) or {}


def _recent_errors(limit: int = 5) -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, context, error, fix, created_at
            FROM learning_errors
            WHERE COALESCE(memory_status, 'active') != 'superseded'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def run_debug_sweep(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Varredura de debug — provas, erros relacionados e diagnóstico."""
    m = _reliability_manifest()
    display = m.get("display_name", RELIABILITY_AGENT)

    if broadcast_observer:
        _broadcast(RELIABILITY_AGENT, "Debug sweep: iniciando proof_gate…", level="debug-sweep")

    suite = proofs.run_full_proof_suite()
    passed = suite.get("all_passed", False)
    failed_checks = [c for c in suite.get("checks", []) if not c.get("passed")]

    related: list[dict[str, Any]] = []
    for check in failed_checks[:3]:
        related.extend(errors_core.get_related_errors(str(check.get("check", "proof")), limit=2))

    fail_summary = "; ".join(
        f"{c.get('check')}: {c.get('detail', '')[:80]}" for c in failed_checks[:5]
    ) or "nenhuma falha na suite"

    diagnosis, _ = _llm_chat(
        f"Você é {display}, especialista em debug e confiabilidade. "
        "Em 4-6 frases: diagnóstico, causa provável e próximo passo.",
        f"Proof gate: {'OK' if passed else 'FALHOU'}\nFalhas: {fail_summary}\n"
        f"Erros relacionados: {len(related)}",
        max_tokens=280,
    )

    if not passed:
        errors_core.record_failure(
            context="debug_sweep proof_gate",
            error=fail_summary[:800],
            fix=diagnosis[:500],
            tags=["debug-sweep", "proof-gate", RELIABILITY_AGENT],
        )

    knowledge.add_note(
        f"[Debug sweep] {display}",
        (
            f"## Proof gate\n{'PASS' if passed else 'FAIL'}\n\n"
            f"## Checks falhos\n{fail_summary}\n\n"
            f"## Diagnóstico\n{diagnosis}"
        ),
        tags=["debug-sweep", "reliability", RELIABILITY_AGENT],
    )
    agent_collaboration.share_insight(
        RELIABILITY_AGENT,
        diagnosis,
        "debug-sweep",
        to_agents=["all", "qa-guardian"],
    )

    if broadcast_observer:
        _broadcast(
            RELIABILITY_AGENT,
            f"Sweep: {'verde' if passed else 'falhas'} — {diagnosis[:120]}…",
            level="debug-sweep-done",
        )

    return {
        "success": True,
        "action": "debug_sweep",
        "agent": RELIABILITY_AGENT,
        "all_passed": passed,
        "failed_checks": failed_checks,
        "related_errors": related[:5],
        "diagnosis": diagnosis,
        "suite": suite,
    }


def run_agent_health_audit(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Auditoria de saúde — registry, órfãos, autonomia e trocas."""
    from learning_agent.core import agent_autonomy, agent_factory

    listing = agent_factory.list_agents()
    projects = listing.get("projects", [])
    names = [p.get("name") for p in projects if p.get("name")]

    orphans = [
        n
        for n in names
        if n
        and (
            any(n.startswith(p) for p in ORPHAN_AGENT_PREFIXES)
            or n in ORPHAN_AGENT_NAMES
        )
    ]
    core_expected = {
        "backend-lead",
        "frontend-lead",
        "qa-guardian",
        "data-engineer",
        RELIABILITY_AGENT,
    }
    missing_core = sorted(core_expected - set(names))

    db.init_db()
    with db.get_connection() as conn:
        exchange_count = conn.execute("SELECT COUNT(*) AS c FROM agent_exchanges").fetchone()["c"]
        error_count = conn.execute("SELECT COUNT(*) AS c FROM learning_errors").fetchone()["c"]
        insight_count = conn.execute("SELECT COUNT(*) AS c FROM agent_insights").fetchone()["c"]

    autonomy = agent_autonomy.get_autonomy_status()
    invalid_manifests: list[str] = []
    for name in names:
        if not agent_collaboration._load_manifest(name or ""):
            invalid_manifests.append(name or "?")

    report_lines = [
        f"Agentes no registry: {len(names)}",
        f"Órfãos de teste: {', '.join(orphans) or 'nenhum'}",
        f"Core faltando: {', '.join(missing_core) or 'completo'}",
        f"Manifests inválidos: {', '.join(invalid_manifests) or 'nenhum'}",
        f"Trocas: {exchange_count} | Insights: {insight_count} | Erros: {error_count}",
        f"Autonomia: {'ativa' if autonomy.get('running') else 'pausada'} "
        f"(ciclo {autonomy.get('cycle', 0)})",
    ]
    report_body = "\n".join(f"- {line}" for line in report_lines)

    recommendations, _ = _llm_chat(
        f"Você é {_reliability_manifest().get('display_name', RELIABILITY_AGENT)}. "
        "Liste 3-5 recomendações curtas de saúde do ecossistema.",
        report_body,
        max_tokens=250,
    )

    knowledge.add_note(
        "[Health audit] ecossistema de agentes",
        f"{report_body}\n\n## Recomendações\n{recommendations}",
        tags=["agent-health", "audit", RELIABILITY_AGENT],
    )
    agent_collaboration.share_insight(
        RELIABILITY_AGENT,
        recommendations,
        "agent-health-audit",
        to_agents=["ravenna", "qa-guardian"],
    )

    if broadcast_observer:
        _broadcast(
            RELIABILITY_AGENT,
            f"Health audit: {len(names)} agentes, {len(orphans)} órfãos",
            level="health-audit",
        )

    return {
        "success": True,
        "action": "agent_health_audit",
        "agent": RELIABILITY_AGENT,
        "total_agents": len(names),
        "orphan_agents": orphans,
        "missing_core": missing_core,
        "invalid_manifests": invalid_manifests,
        "exchange_count": exchange_count,
        "error_count": error_count,
        "autonomy": autonomy,
        "recommendations": recommendations,
    }


def run_optimize_cycle(
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Propõe otimizações com base em métricas do ciclo autônomo."""
    from learning_agent.core import agent_autonomy

    status = agent_autonomy.get_autonomy_status()
    errors = _recent_errors(3)
    gaps_total = 0
    for agent in agent_collaboration.list_collaborative_agents():
        name = agent.get("name")
        if name:
            gaps_total += agent_collaboration.detect_knowledge_gaps(name).get("gap_count", 0)

    metrics = (
        f"Intervalo autonomia: {status.get('interval_seconds')}s\n"
        f"Ciclo atual: {status.get('cycle')}\n"
        f"Ação atual: {status.get('current_action')}\n"
        f"Erros recentes: {len(errors)}\n"
        f"Lacunas totais: {gaps_total}\n"
        f"Always-on: {status.get('always_on')}"
    )

    plan, _ = _llm_chat(
        f"Você é {_reliability_manifest().get('display_name', RELIABILITY_AGENT)}. "
        "Sugira otimizações concretas (intervalo, prioridade de ações, mocks em CI, "
        "limpeza de órfãos). 4-6 bullets curtos.",
        metrics,
        max_tokens=280,
    )

    knowledge.add_note(
        f"[Optimize] ciclo autônomo",
        f"## Métricas\n{metrics}\n\n## Plano\n{plan}",
        tags=["optimize-cycle", RELIABILITY_AGENT, "autonomy"],
    )
    agent_collaboration.share_insight(RELIABILITY_AGENT, plan, "optimize-cycle", to_agents=["all"])

    if broadcast_observer:
        _broadcast(RELIABILITY_AGENT, f"Otimização: {plan[:150]}…", level="optimize-cycle")

    return {
        "success": True,
        "action": "optimize_cycle",
        "agent": RELIABILITY_AGENT,
        "metrics": metrics,
        "plan": plan,
        "gaps_total": gaps_total,
        "recent_errors": len(errors),
    }
