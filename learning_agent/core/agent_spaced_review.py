"""Revisão espaçada (SM-2) por domínio de cada agente."""

from __future__ import annotations

from typing import Any

from learning_agent import db
from learning_agent.core import agent_collaboration, knowledge, llm as llm_core, quiz

def get_due_reviews(agent: str, limit: int = 5) -> list[dict[str, Any]]:
    tags = [t.lower() for t in agent_collaboration._learning_tags(agent)]
    tags.append(agent.replace("-", " "))

    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT qi.id, qi.topic, qi.question, qi.answer, qi.next_review
            FROM quiz_items qi
            WHERE qi.next_review IS NULL OR qi.next_review <= ?
            ORDER BY qi.next_review IS NULL DESC, qi.next_review ASC
            LIMIT ?
            """,
            (db._utcnow(), limit * 4),
        ).fetchall()

    due: list[dict[str, Any]] = []
    for row in rows:
        topic = str(row["topic"]).lower()
        if any(tag in topic for tag in tags if len(tag) >= 3):
            due.append(dict(row))
        if len(due) >= limit:
            break
    return due


def run_spaced_review(
    agent: str | None = None,
    *,
    max_items: int = 3,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Drill SM-2: revisa quizzes vencidos do domínio do agente."""
    from learning_agent.core.agent_capability import CORE_AGENTS

    slug = agent or CORE_AGENTS[0]
    due = get_due_reviews(slug, limit=max_items)
    reviewed: list[dict[str, Any]] = []

    if not due:
        q = quiz.create_quiz(topic=f"peer-{slug}", count=min(2, max_items))
        for item in q.get("questions", []):
            due.append({**item, "answer": ""})

    manifest = agent_collaboration._load_manifest(slug) or {}
    display = manifest.get("display_name", slug)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug, f"Revisão SM-2: {len(due)} item(ns)", level="spaced-review"
        )

    from learning_agent.core.agent_learning_loop import _evaluate_quiz_answer

    for item in due[:max_items]:
        qid = item.get("id")
        question = item.get("question", "O que aprendemos?")
        expected = str(item.get("answer", ""))
        if qid and not expected:
            db.init_db()
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT answer FROM quiz_items WHERE id = ?", (int(qid),)
                ).fetchone()
                if row:
                    expected = str(row["answer"])

        try:
            answer, _ = llm_core.chat_with_fallback(
                [
                    {"role": "system", "content": f"Você é {display}. Responda o quiz de forma concisa."},
                    {"role": "user", "content": question},
                ],
                max_tokens=150,
                temperature=0.4,
            )
        except Exception:
            answer = "revisão pendente"

        correct = _evaluate_quiz_answer(expected, answer) if expected else len(answer.strip()) >= 40
        if qid:
            quiz.record_answer(int(qid), correct=correct, response=answer[:400])
        reviewed.append({"quiz_id": qid, "question": question, "answer": answer, "correct": correct})

    summary = f"Revisados {len(reviewed)} itens SM-2 para {slug}"
    knowledge.add_note(
        f"[SM-2] {slug}",
        "\n".join(f"Q: {r['question']}\nA: {r['answer']}" for r in reviewed),
        tags=["spaced-review", f"agent:{slug}"],
    )
    agent_collaboration.share_insight(slug, summary, "spaced-review", to_agents=["all"])

    return {
        "success": True,
        "action": "spaced_review",
        "agent": slug,
        "reviewed": reviewed,
        "count": len(reviewed),
    }
