"""Audit and reversible curation for Ravenna's durable memory.

The default path never deletes, vacuums, or reindexes data. Curation is a
reviewable dry-run unless apply=True is explicitly provided.
"""

from __future__ import annotations

from typing import Any

from learning_agent import db, rag


MEMORY_TABLES = [
    "learning_notes",
    "learning_errors",
    "knowledge_edges",
    "agent_insights",
    "agent_exchanges",
    "quiz_items",
    "quiz_attempts",
    "study_sessions",
    "distillation_pairs",
    "chat_messages",
    "chat_conversations",
]

CURATION_TARGETS: dict[str, tuple[str, ...]] = {
    "learning_notes": ("title", "content"),
    "learning_errors": ("context", "error", "fix"),
    "knowledge_edges": ("from_concept", "to_concept", "relation", "source_ref"),
}


def run_memory_audit(*, limit: int = 10, include_chroma: bool = True) -> dict[str, Any]:
    """Return a read-only memory health report with dry-run recommendations."""

    safe_limit = max(1, min(int(limit or 10), 100))
    db.init_db()
    with db.get_connection() as conn:
        table_counts = {table: _count_table(conn, table) for table in MEMORY_TABLES}
        duplicate_note_titles = _duplicate_rows(
            conn,
            table="learning_notes",
            value_column="title",
            label="title",
            limit=safe_limit,
        )
        duplicate_errors = _duplicate_rows(
            conn,
            table="learning_errors",
            value_column="error",
            label="error",
            limit=safe_limit,
        )
        duplicate_edges = _duplicate_edges(conn, safe_limit)
        top_note_tags = _top_rows(
            conn,
            table="learning_notes",
            value_column="tags",
            label="tags",
            limit=safe_limit,
        )
        curation_status = _curation_status(conn)

    chroma_count = _chroma_count() if include_chroma else None
    findings = _build_findings(
        table_counts=table_counts,
        duplicate_note_titles=duplicate_note_titles,
        duplicate_errors=duplicate_errors,
        duplicate_edges=duplicate_edges,
        chroma_count=chroma_count,
    )
    cleanup_plan = _build_cleanup_plan(findings)

    return {
        "success": True,
        "mode": "read_only",
        "dry_run": True,
        "table_counts": table_counts,
        "chroma_documents": chroma_count,
        "duplicate_note_titles": duplicate_note_titles,
        "duplicate_errors": duplicate_errors,
        "duplicate_knowledge_edges": duplicate_edges,
        "top_note_tags": top_note_tags,
        "curation_status": curation_status,
        "findings": findings,
        "cleanup_plan": cleanup_plan,
        "safety": {
            "mutates_data": False,
            "deletes_data": False,
            "reindexes_chroma": False,
            "requires_manual_approval_for_cleanup": True,
        },
    }


def run_memory_curation(
    *,
    apply: bool = False,
    limit: int = 10,
    max_batches: int = 1,
    include_groups: bool = True,
) -> dict[str, Any]:
    """Plan or apply reversible duplicate superseding.

    apply=False is a pure dry-run. apply=True does not delete; it marks duplicate
    rows as superseded and links them to the canonical lowest-id row.
    """

    safe_limit = max(1, min(int(limit or 10), 100))
    safe_batches = max(1, min(int(max_batches or 1), 10_000))
    db.init_db()
    now = db._utcnow()
    results: list[dict[str, Any]] = []
    total_candidates = 0
    total_marked = 0
    total_groups = 0

    for table, columns in CURATION_TARGETS.items():
        with db.get_connection() as conn:
            table_totals = _duplicate_totals(conn, table, columns)
            table_candidates = table_totals["candidate_duplicates"]
            table_groups = table_totals["groups"]
            sample_groups = _duplicate_groups(conn, table, columns, safe_limit) if include_groups else []
            table_marked = 0
            if apply:
                table_marked = _mark_table_superseded(conn, table, columns, now)
            total_candidates += table_candidates
            total_marked += table_marked
            total_groups += table_groups
            results.append(
                {
                    "table": table,
                    "identity_columns": list(columns),
                    "groups": sample_groups,
                    "groups_considered": table_groups,
                    "candidate_duplicates": table_candidates,
                    "marked_superseded": table_marked,
                }
            )

    return {
        "success": True,
        "dry_run": not apply,
        "apply": apply,
        "deletes_data": False,
        "reindexes_chroma": False,
        "max_batches": safe_batches,
        "groups_considered": total_groups,
        "total_candidate_duplicates": total_candidates,
        "total_marked_superseded": total_marked,
        "tables": results,
    }


def restore_superseded_memory(
    *,
    table: str | None = None,
    canonical_id: int | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Restore superseded rows back to active status.

    This is the inverse maintenance tool for curation. It is intentionally
    bounded by limit so a mistaken call remains controllable.
    """

    safe_limit = max(1, min(int(limit or 1000), 100_000))
    targets = [table] if table else list(CURATION_TARGETS)
    invalid = [target for target in targets if target not in CURATION_TARGETS]
    if invalid:
        return {"success": False, "error": f"Unsupported memory table: {', '.join(invalid)}"}

    db.init_db()
    restored: dict[str, int] = {}
    with db.get_connection() as conn:
        for target in targets:
            params: list[Any] = []
            extra = ""
            if canonical_id is not None:
                extra = " AND canonical_id = ?"
                params.append(canonical_id)
            cursor = conn.execute(
                f"""
                UPDATE {target}
                SET memory_status = 'active',
                    canonical_id = NULL,
                    superseded_at = NULL
                WHERE id IN (
                    SELECT id
                    FROM {target}
                    WHERE memory_status = 'superseded'{extra}
                    ORDER BY id ASC
                    LIMIT ?
                )
                """,
                (*params, safe_limit),
            )
            restored[target] = int(cursor.rowcount or 0)
    return {
        "success": True,
        "restored": restored,
        "total_restored": sum(restored.values()),
        "deletes_data": False,
    }


def _count_table(conn: Any, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"] or 0)


def _duplicate_rows(
    conn: Any,
    *,
    table: str,
    value_column: str,
    label: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {value_column} AS value, COUNT(*) AS count, MIN(id) AS first_id, MAX(id) AS last_id
        FROM {table}
        WHERE TRIM(COALESCE({value_column}, '')) != ''
          AND COALESCE(memory_status, 'active') != 'superseded'
        GROUP BY {value_column}
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            label: _shorten(row["value"]),
            "count": int(row["count"] or 0),
            "first_id": row["first_id"],
            "last_id": row["last_id"],
        }
        for row in rows
    ]


def _top_rows(
    conn: Any,
    *,
    table: str,
    value_column: str,
    label: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT {value_column} AS value, COUNT(*) AS count
        FROM {table}
        WHERE TRIM(COALESCE({value_column}, '')) != ''
          AND COALESCE(memory_status, 'active') != 'superseded'
        GROUP BY {value_column}
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{label: _shorten(row["value"]), "count": int(row["count"] or 0)} for row in rows]


def _duplicate_edges(conn: Any, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT from_concept, to_concept, relation, source_ref, COUNT(*) AS count
        FROM knowledge_edges
        WHERE COALESCE(memory_status, 'active') != 'superseded'
        GROUP BY from_concept, to_concept, relation, source_ref
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "from": _shorten(row["from_concept"], 80),
            "to": _shorten(row["to_concept"], 80),
            "relation": row["relation"],
            "source_ref": _shorten(row["source_ref"], 120),
            "count": int(row["count"] or 0),
        }
        for row in rows
    ]


def _curation_status(conn: Any) -> dict[str, dict[str, int]]:
    status: dict[str, dict[str, int]] = {}
    for table in CURATION_TARGETS:
        rows = conn.execute(
            f"""
            SELECT COALESCE(memory_status, 'active') AS status, COUNT(*) AS count
            FROM {table}
            GROUP BY COALESCE(memory_status, 'active')
            """
        ).fetchall()
        status[table] = {str(row["status"]): int(row["count"] or 0) for row in rows}
    return status


def _duplicate_groups(
    conn: Any,
    table: str,
    columns: tuple[str, ...],
    limit: int,
) -> list[dict[str, Any]]:
    select_columns = ", ".join(columns)
    group_columns = ", ".join(columns)
    active_clause = "COALESCE(memory_status, 'active') != 'superseded'"
    rows = conn.execute(
        f"""
        SELECT {select_columns}, MIN(id) AS canonical_id, COUNT(*) AS count
        FROM {table}
        WHERE {active_clause}
        GROUP BY {group_columns}
        HAVING COUNT(*) > 1
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    groups: list[dict[str, Any]] = []
    for row in rows:
        values = {column: row[column] for column in columns}
        canonical_id = int(row["canonical_id"])
        count = int(row["count"] or 0)
        sample_duplicate_ids = _sample_duplicate_ids(conn, table, columns, values, canonical_id)
        groups.append(
            {
                "canonical_id": canonical_id,
                "duplicate_count": max(0, count - 1),
                "total_count": count,
                "identity": {key: _shorten(value) for key, value in values.items()},
                "sample_duplicate_ids": sample_duplicate_ids,
            }
        )
    return groups


def _duplicate_totals(conn: Any, table: str, columns: tuple[str, ...]) -> dict[str, int]:
    group_columns = ", ".join(columns)
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS groups, COALESCE(SUM(count - 1), 0) AS candidate_duplicates
        FROM (
            SELECT COUNT(*) AS count
            FROM {table}
            WHERE COALESCE(memory_status, 'active') != 'superseded'
            GROUP BY {group_columns}
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()
    return {
        "groups": int(row["groups"] or 0),
        "candidate_duplicates": int(row["candidate_duplicates"] or 0),
    }


def _mark_table_superseded(
    conn: Any,
    table: str,
    columns: tuple[str, ...],
    now: str,
) -> int:
    temp_table = f"tmp_memory_canonical_{table}"
    select_columns = ", ".join(columns)
    group_columns = ", ".join(columns)
    identity_match = " AND ".join(f"{temp_table}.{column} = {table}.{column}" for column in columns)
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(
        f"""
        CREATE TEMP TABLE {temp_table} AS
        SELECT MIN(id) AS canonical_id,
               COUNT(*) AS group_count,
               {select_columns}
        FROM {table}
        WHERE COALESCE(memory_status, 'active') != 'superseded'
        GROUP BY {group_columns}
        HAVING COUNT(*) > 1
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{temp_table}_canonical ON {temp_table}(canonical_id)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{temp_table}_identity ON {temp_table}({group_columns})"
    )
    conn.execute(
        f"""
        UPDATE {table}
        SET occurrence_count = MAX(
                COALESCE(occurrence_count, 1),
                COALESCE((SELECT group_count FROM {temp_table} WHERE {temp_table}.canonical_id = {table}.id LIMIT 1), 1)
            )
        WHERE id IN (SELECT canonical_id FROM {temp_table})
        """
    )
    before = int(getattr(conn, "total_changes", 0))
    conn.execute(
        f"""
        UPDATE {table}
        SET memory_status = 'superseded',
            canonical_id = (
                SELECT canonical_id
                FROM {temp_table}
                WHERE {identity_match}
                LIMIT 1
            ),
            superseded_at = ?
        WHERE COALESCE(memory_status, 'active') != 'superseded'
          AND EXISTS (
            SELECT 1
            FROM {temp_table}
            WHERE {identity_match}
          )
          AND id != (
            SELECT canonical_id
            FROM {temp_table}
            WHERE {identity_match}
            LIMIT 1
          )
        """,
        (now,),
    )
    after = int(getattr(conn, "total_changes", before))
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    return max(0, after - before)


def _sample_duplicate_ids(
    conn: Any,
    table: str,
    columns: tuple[str, ...],
    values: dict[str, Any],
    canonical_id: int,
    limit: int = 5,
) -> list[int]:
    where, params = _identity_where(columns, values)
    rows = conn.execute(
        f"""
        SELECT id FROM {table}
        WHERE id != ? AND {where}
        ORDER BY id ASC
        LIMIT ?
        """,
        (canonical_id, *params, limit),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _mark_group_superseded(
    conn: Any,
    table: str,
    columns: tuple[str, ...],
    group: dict[str, Any],
    now: str,
) -> int:
    identity = _identity_values_for_canonical(conn, table, columns, int(group["canonical_id"]))
    where, params = _identity_where(columns, identity)
    canonical_id = int(group["canonical_id"])
    cursor = conn.execute(
        f"""
        UPDATE {table}
        SET memory_status = 'superseded',
            canonical_id = ?,
            superseded_at = ?
        WHERE id != ?
          AND COALESCE(memory_status, 'active') != 'superseded'
          AND {where}
        """,
        (canonical_id, now, canonical_id, *params),
    )
    conn.execute(
        f"UPDATE {table} SET occurrence_count = MAX(COALESCE(occurrence_count, 1), ?) WHERE id = ?",
        (int(group["total_count"]), canonical_id),
    )
    return int(cursor.rowcount or 0)


def _identity_where(columns: tuple[str, ...], values: dict[str, Any]) -> tuple[str, list[Any]]:
    return " AND ".join(f"{column} = ?" for column in columns), [values[column] for column in columns]


def _identity_values_for_canonical(
    conn: Any,
    table: str,
    columns: tuple[str, ...],
    canonical_id: int,
) -> dict[str, Any]:
    select_columns = ", ".join(columns)
    row = conn.execute(
        f"SELECT {select_columns} FROM {table} WHERE id = ?",
        (canonical_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"Canonical row {canonical_id} not found in {table}")
    return {column: row[column] for column in columns}


def _chroma_count() -> int | None:
    try:
        return int(rag.get_collection().count())
    except Exception:
        return None


def _build_findings(
    *,
    table_counts: dict[str, int],
    duplicate_note_titles: list[dict[str, Any]],
    duplicate_errors: list[dict[str, Any]],
    duplicate_edges: list[dict[str, Any]],
    chroma_count: int | None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    note_count = table_counts.get("learning_notes", 0)
    error_count = table_counts.get("learning_errors", 0)
    edge_count = table_counts.get("knowledge_edges", 0)

    if note_count > 50_000:
        findings.append(_finding("high_note_volume", "high", f"{note_count} learning notes stored."))
    if error_count > 25_000:
        findings.append(_finding("high_error_volume", "high", f"{error_count} learning errors stored."))
    if edge_count > 50_000:
        findings.append(_finding("high_graph_volume", "medium", f"{edge_count} knowledge edges stored."))

    if duplicate_note_titles and duplicate_note_titles[0]["count"] > 100:
        findings.append(
            _finding(
                "duplicate_note_titles",
                "high",
                f"Top duplicated note title appears {duplicate_note_titles[0]['count']} times.",
            )
        )
    if duplicate_errors and duplicate_errors[0]["count"] > 100:
        findings.append(
            _finding(
                "duplicate_errors",
                "high",
                f"Top duplicated error appears {duplicate_errors[0]['count']} times.",
            )
        )
    if duplicate_edges:
        findings.append(
            _finding(
                "duplicate_graph_edges",
                "medium",
                f"Top duplicated edge appears {duplicate_edges[0]['count']} times.",
            )
        )
    if chroma_count is not None and note_count and chroma_count < max(10, note_count // 20):
        findings.append(
            _finding(
                "sqlite_chroma_skew",
                "medium",
                f"SQLite has {note_count} notes while Chroma has {chroma_count} documents.",
            )
        )
    if not findings:
        findings.append(_finding("memory_healthy", "low", "No high-volume duplicate hotspots detected."))
    return findings


def _build_cleanup_plan(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = [
        {
            "step": "dedupe_guard",
            "dry_run": True,
            "action": "Add content/title hash checks before inserting new notes and repeated errors.",
        },
        {
            "step": "canonicalize_consolidations",
            "dry_run": True,
            "action": "Mark raw repeated notes as candidates for superseded status after a reviewed master note exists.",
        },
        {
            "step": "retrieval_filters",
            "dry_run": True,
            "action": "Prefer canonical, project-scoped, recent, and verified memory during get_context_for_task.",
        },
    ]
    if any(item["id"] == "duplicate_errors" for item in findings):
        plan.insert(
            0,
            {
                "step": "error_rate_limit",
                "dry_run": True,
                "action": "Stop recording identical learning_errors after a small daily threshold; increment a counter instead.",
            },
        )
    return plan


def _finding(identifier: str, severity: str, message: str) -> dict[str, str]:
    return {"id": identifier, "severity": severity, "message": message}


def _shorten(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
