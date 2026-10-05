from typing import Any

from learning_agent import db
from learning_agent import rag
from learning_agent import sync
from learning_agent.core import graph as graph_core
from learning_agent.core import proofs


def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    raw_limit = max(limit, limit * 5)
    results = rag.search_knowledge(query, limit=raw_limit)
    return _rank_memory_results(_active_memory_results(results))[:limit]


def _active_memory_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in results:
        doc_id = str(item.get("id") or "")
        ref = _memory_ref_from_doc_id(doc_id)
        if not ref:
            filtered.append(item)
            continue
        table, row_id = ref
        status = _memory_status(table, row_id)
        if status.get("memory_status") in {"superseded", "missing"}:
            continue
        if status:
            metadata = dict(item.get("metadata") or {})
            metadata.update(status)
            item = {**item, "metadata": metadata}
        filtered.append(item)
    return filtered


def _rank_memory_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def score(item: dict[str, Any]) -> tuple[float, int]:
        metadata = item.get("metadata") or {}
        distance = item.get("distance")
        similarity = 0.0 if distance is None else -float(distance)
        occurrences = int(metadata.get("occurrence_count") or 1)
        return (similarity, occurrences)

    return sorted(results, key=score, reverse=True)


def _memory_ref_from_doc_id(doc_id: str) -> tuple[str, int] | None:
    prefixes = {
        "note:": "learning_notes",
        "error:": "learning_errors",
        "graph:": "knowledge_edges",
    }
    for prefix, table in prefixes.items():
        if doc_id.startswith(prefix) and doc_id[len(prefix):].isdigit():
            return table, int(doc_id[len(prefix):])
    return None


def _memory_status(table: str, row_id: int) -> dict[str, Any]:
    try:
        db.init_db()
        with db.get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT COALESCE(memory_status, 'active') AS memory_status,
                       canonical_id,
                       COALESCE(occurrence_count, 1) AS occurrence_count
                FROM {table}
                WHERE id = ?
                """,
                (row_id,),
            ).fetchone()
    except Exception:
        return {}
    if not row:
        return {"memory_status": "missing"}
    return {
        "memory_status": row["memory_status"] or "active",
        "canonical_id": row["canonical_id"],
        "occurrence_count": int(row["occurrence_count"] or 1),
    }


def add_note(
    title: str,
    content: str,
    tags: list[str] | None = None,
    sync_cloud: bool = True,
) -> dict[str, Any]:
    db.init_db()
    now = db._utcnow()
    tag_list = tags or []

    with db.get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, title, content, tags
            FROM learning_notes
            WHERE title = ? AND content = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (title, content),
        ).fetchone()
        if existing:
            try:
                conn.execute(
                    "UPDATE learning_notes SET occurrence_count = COALESCE(occurrence_count, 1) + 1, updated_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
            except Exception:
                pass
            result = {
                "id": existing["id"],
                "title": existing["title"],
                "content": existing["content"],
                "tags": db.parse_tags(existing["tags"] or "[]"),
                "note_id": existing["id"],
                "duplicate_skipped": True,
            }
            return proofs.attach_proofs(result)

        cursor = conn.execute(
            """
            INSERT INTO learning_notes (title, content, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title, content, db.dump_tags(tag_list), now, now),
        )
        note_id = cursor.lastrowid

    doc_id = f"note:{note_id}"
    rag.index_document(
        doc_id,
        f"{title}\n\n{content}",
        {"type": "note", "title": title, "tags": ",".join(tag_list)},
    )

    if len(tag_list) >= 2:
        try:
            graph_core.add_edge(tag_list[0], tag_list[1], "tagged_with", 0.8, f"note:{note_id}")
        except Exception:
            pass

    result = {"id": note_id, "title": title, "content": content, "tags": tag_list, "note_id": note_id}
    if sync_cloud:
        result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)


def index_text(title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
    tag_list = tags or []
    doc_id = f"doc:{title.replace(' ', '_').lower()}"
    rag.index_document(
        doc_id,
        content,
        {"type": "document", "title": title, "tags": ",".join(tag_list)},
    )
    result = {"id": doc_id, "title": title, "tags": tag_list}
    return sync.attach_cloud_sync(result)
