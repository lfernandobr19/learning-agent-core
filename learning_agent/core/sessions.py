"""Memória de sessões — continuidade entre conversas e máquinas."""

from __future__ import annotations

import json
from typing import Any

from learning_agent import db
from learning_agent import rag
from learning_agent import sync
from learning_agent.core import proofs


def record_session(
    summary: str,
    topics: list[str] | None = None,
    decisions: list[str] | None = None,
    duration_minutes: int = 0,
    sync_cloud: bool = True,
) -> dict[str, Any]:
    db.init_db()
    now = db._utcnow()
    topic_list = topics or []
    decision_list = decisions or []

    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_sessions (summary, topics, decisions, duration_minutes, started_at, ended_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                summary,
                json.dumps(topic_list, ensure_ascii=False),
                json.dumps(decision_list, ensure_ascii=False),
                duration_minutes,
                now,
                now,
            ),
        )
        session_id = int(cursor.lastrowid)

    doc_id = f"session:{session_id}"
    rag.index_document(
        doc_id,
        f"Sessão #{session_id}\nTópicos: {', '.join(topic_list)}\n\n{summary}",
        {"type": "session", "session_id": str(session_id), "tags": "session,memory"},
    )

    result: dict[str, Any] = {
        "success": True,
        "session_id": session_id,
        "summary": summary[:200],
        "topics": topic_list,
    }
    if sync_cloud:
        result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def get_recent_sessions(limit: int = 5) -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, summary, topics, decisions, duration_minutes, started_at
            FROM agent_sessions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    sessions: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["topics"] = json.loads(item.get("topics") or "[]")
        item["decisions"] = json.loads(item.get("decisions") or "[]")
        sessions.append(item)
    return sessions


def recall_sessions(query: str, limit: int = 5) -> list[dict[str, Any]]:
    hits = rag.search_knowledge(query, limit=limit * 2)
    session_ids: list[int] = []
    for hit in hits:
        if hit.get("metadata", {}).get("type") == "session":
            sid = hit["metadata"].get("session_id")
            if sid and str(sid).isdigit():
                session_ids.append(int(sid))

    if not session_ids:
        db.init_db()
        with db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, summary, topics, decisions, started_at
                FROM agent_sessions
                WHERE summary LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
        return [dict(r) for r in rows]

    db.init_db()
    placeholders = ",".join("?" * len(session_ids[:limit]))
    with db.get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT id, summary, topics, decisions, started_at
            FROM agent_sessions
            WHERE id IN ({placeholders})
            ORDER BY id DESC
            """,
            session_ids[:limit],
        ).fetchall()
    return [dict(r) for r in rows]
