"""Aprendizado por falha — registra erros e correções para não repetir."""

from __future__ import annotations

import json
from typing import Any

from learning_agent import db
from learning_agent import rag
from learning_agent import sync
from learning_agent.core import knowledge, proofs


def record_failure(
    context: str,
    error: str,
    fix: str = "",
    tags: list[str] | None = None,
    sync_cloud: bool = True,
) -> dict[str, Any]:
    db.init_db()
    now = db._utcnow()
    tag_list = tags or ["failure", "lesson-learned"]

    with db.get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, context
            FROM learning_errors
            WHERE context = ? AND error = ? AND fix = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (context, error, fix),
        ).fetchone()
        if existing:
            try:
                conn.execute(
                    "UPDATE learning_errors SET occurrence_count = COALESCE(occurrence_count, 1) + 1 WHERE id = ?",
                    (existing["id"],),
                )
            except Exception:
                pass
            result: dict[str, Any] = {
                "success": True,
                "error_id": int(existing["id"]),
                "context": existing["context"],
                "note_id": None,
                "duplicate_skipped": True,
            }
            if sync_cloud:
                result = sync.attach_cloud_sync(result)
            return proofs.attach_proofs(result)

        cursor = conn.execute(
            """
            INSERT INTO learning_errors (context, error, fix, tags, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (context, error, fix, json.dumps(tag_list, ensure_ascii=False), now),
        )
        error_id = int(cursor.lastrowid)

    content = f"Contexto: {context}\nErro: {error}\nCorreção: {fix or '(pendente)'}"
    rag.index_document(
        f"error:{error_id}",
        content,
        {"type": "learning_error", "error_id": str(error_id), "tags": ",".join(tag_list)},
    )

    note = None
    if fix:
        note = knowledge.add_note(
            title=f"[Lição] {context[:60]}",
            content=f"**Erro:** {error}\n\n**Correção:** {fix}",
            tags=tag_list + ["auto-from-failure"],
            sync_cloud=sync_cloud,
        )

    result: dict[str, Any] = {
        "success": True,
        "error_id": error_id,
        "context": context,
        "note_id": note.get("note_id") if note else None,
    }
    if sync_cloud:
        result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def get_related_errors(query: str, limit: int = 5) -> list[dict[str, Any]]:
    hits = rag.search_knowledge(query, limit=limit * 2)
    hits = knowledge._active_memory_results(hits)
    error_ids: list[int] = []
    for hit in hits:
        if hit.get("metadata", {}).get("type") == "learning_error":
            eid = hit["metadata"].get("error_id")
            if eid and str(eid).isdigit():
                error_ids.append(int(eid))

    db.init_db()
    if error_ids:
        placeholders = ",".join("?" * len(error_ids[:limit]))
        with db.get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, context, error, fix, created_at
                FROM learning_errors
                WHERE id IN ({placeholders})
                  AND COALESCE(memory_status, 'active') != 'superseded'
                ORDER BY id DESC
                """,
                error_ids[:limit],
            ).fetchall()
        return [dict(r) for r in rows]

    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, context, error, fix, created_at
            FROM learning_errors
            WHERE (context LIKE ? OR error LIKE ?)
              AND COALESCE(memory_status, 'active') != 'superseded'
            ORDER BY id DESC
            LIMIT ?
            """,
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def maybe_record_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Registra falha automaticamente quando verified=false."""
    if result.get("verified") is not False:
        return None

    proofs_data = result.get("proofs", {})
    failed = [c for c in proofs_data.get("checks", []) if not c.get("passed")]
    error_detail = "; ".join(f"{c.get('check')}: {c.get('detail', '')}" for c in failed[:3])
    if not error_detail:
        error_detail = "verified=false sem detalhe"

    context = result.get("title") or result.get("topic") or result.get("url") or "operação de aprendizado"
    return record_failure(
        context=str(context)[:200],
        error=error_detail[:1000],
        fix="Revisar e repetir com provas reais até verified=true",
        tags=["auto-failure"],
        sync_cloud=True,
    )
