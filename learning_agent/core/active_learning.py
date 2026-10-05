"""Active learning — Ravenna escolhe o que estudar e aprende sozinha."""

from __future__ import annotations

from typing import Any

from learning_agent import db
from learning_agent.config import ACTIVE_LEARN_MAX_PER_RUN, AUTO_ACTIVE_LEARN
from learning_agent.core import curriculum, progress, web
from learning_agent.core import graph as graph_core
from learning_agent import sync
from learning_agent.core import proofs


def _queue_topic(topic: str, reason: str) -> int:
    db.init_db()
    now = db._utcnow()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO learning_queue (topic, reason, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (topic, reason, now),
        )
        return int(cursor.lastrowid)


def suggest_learning(limit: int = 5) -> dict[str, Any]:
    """Sugere tópicos para estudar com base em lacunas."""
    prog = progress.get_progress()
    next_curriculum = curriculum.get_next_topic()
    suggestions: list[dict[str, str]] = []

    for area in prog.get("weak_areas", [])[:limit]:
        suggestions.append({"topic": area, "reason": "área fraca em quiz"})

    if next_curriculum.get("found") and next_curriculum.get("status") == "in_progress":
        topic = next_curriculum["next_topic"]["title"]
        suggestions.append({"topic": topic, "reason": "próximo no currículo"})

    db.init_db()
    with db.get_connection() as conn:
        low_sim = conn.execute(
            """
            SELECT topic, similarity_score FROM distillation_pairs
            WHERE similarity_score < 0.4
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    for row in low_sim:
        suggestions.append(
            {"topic": row["topic"], "reason": f"distillation fraca (sim={row['similarity_score']})"}
        )

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for s in suggestions:
        key = s["topic"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return {"suggestions": unique[:limit], "count": len(unique[:limit])}


def run_active_learning(max_items: int | None = None) -> dict[str, Any]:
    """Executa aprendizado ativo: pesquisa web + indexa tópicos sugeridos."""
    limit = max_items or ACTIVE_LEARN_MAX_PER_RUN
    suggestions = suggest_learning(limit=limit)
    learned: list[dict[str, Any]] = []
    errors: list[str] = []

    for item in suggestions["suggestions"][:limit]:
        topic = item["topic"]
        queue_id = _queue_topic(topic, item["reason"])
        try:
            result = web.search_and_learn(topic, limit=2, tags=["active-learning", "auto"])
            graph_core.add_edge(topic.lower(), "active-learning", "studied_via", 1.0, f"queue:{queue_id}")
            learned.append({"topic": topic, "queue_id": queue_id, **result})
            db.init_db()
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE learning_queue SET status='done', completed_at=? WHERE id=?",
                    (db._utcnow(), queue_id),
                )
        except Exception as exc:
            errors.append(f"{topic}: {exc}")
            db.init_db()
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE learning_queue SET status='failed', completed_at=? WHERE id=?",
                    (db._utcnow(), queue_id),
                )

    result: dict[str, Any] = {
        "success": len(errors) == 0,
        "learned_count": len(learned),
        "learned": learned,
        "errors": errors,
    }
    result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def maybe_auto_learn() -> dict[str, Any] | None:
    if not AUTO_ACTIVE_LEARN:
        return None
    return run_active_learning()
