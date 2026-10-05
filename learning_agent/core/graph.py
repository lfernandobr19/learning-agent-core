"""Grafo de conhecimento — conceitos ligados por relações."""

from __future__ import annotations

import json
import re
from typing import Any

from learning_agent import db
from learning_agent import rag


def add_edge(
    from_concept: str,
    to_concept: str,
    relation: str = "relates_to",
    weight: float = 1.0,
    source_ref: str = "",
) -> dict[str, Any]:
    db.init_db()
    from_c = from_concept.strip().lower()
    to_c = to_concept.strip().lower()
    if not from_c or not to_c or from_c == to_c:
        raise ValueError("Conceitos inválidos")

    now = db._utcnow()
    with db.get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id, weight
            FROM knowledge_edges
            WHERE from_concept = ? AND to_concept = ? AND relation = ? AND source_ref = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (from_c, to_c, relation, source_ref),
        ).fetchone()
        if existing:
            edge_id = int(existing["id"])
            if float(weight) > float(existing["weight"] or 0):
                conn.execute(
                    "UPDATE knowledge_edges SET weight = ?, created_at = ? WHERE id = ?",
                    (weight, now, edge_id),
                )
            try:
                conn.execute(
                    "UPDATE knowledge_edges SET occurrence_count = COALESCE(occurrence_count, 1) + 1 WHERE id = ?",
                    (edge_id,),
                )
            except Exception:
                pass
            return {
                "success": True,
                "edge_id": edge_id,
                "from": from_c,
                "to": to_c,
                "relation": relation,
                "duplicate_skipped": True,
            }

        cursor = conn.execute(
            """
            INSERT INTO knowledge_edges (from_concept, to_concept, relation, weight, source_ref, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (from_c, to_c, relation, weight, source_ref, now),
        )
        edge_id = int(cursor.lastrowid)

    rag.index_document(
        f"graph:{edge_id}",
        f"{from_c} --[{relation}]--> {to_c} (weight={weight})",
        {"type": "graph_edge", "from": from_c, "to": to_c, "relation": relation},
    )
    return {"success": True, "edge_id": edge_id, "from": from_c, "to": to_c, "relation": relation}


def add_edges_from_soft_labels(
    topic: str,
    soft_labels: dict[str, Any],
    source_ref: str = "",
) -> list[dict[str, Any]]:
    topic_c = topic.strip().lower()
    created: list[dict[str, Any]] = []
    for concept, weight in soft_labels.items():
        try:
            w = float(weight)
        except (TypeError, ValueError):
            w = 0.5
        created.append(
            add_edge(topic_c, concept.strip().lower(), "soft_label", w, source_ref)
        )
    return created


def get_related_concepts(concept: str, depth: int = 2, limit: int = 20) -> dict[str, Any]:
    db.init_db()
    concept_c = concept.strip().lower()
    visited: set[str] = {concept_c}
    frontier = [concept_c]
    edges: list[dict[str, Any]] = []

    for _ in range(max(1, depth)):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        with db.get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT from_concept, to_concept, relation, weight
                FROM knowledge_edges
                WHERE (from_concept IN ({placeholders}) OR to_concept IN ({placeholders}))
                  AND COALESCE(memory_status, 'active') != 'superseded'
                ORDER BY weight DESC, occurrence_count DESC
                LIMIT ?
                """,
                (*frontier, *frontier, limit),
            ).fetchall()

        next_frontier: list[str] = []
        for row in rows:
            item = dict(row)
            edges.append(item)
            for node in (item["from_concept"], item["to_concept"]):
                if node not in visited:
                    visited.add(node)
                    next_frontier.append(node)
        frontier = next_frontier

    return {
        "concept": concept_c,
        "nodes": sorted(visited),
        "edges": edges[:limit],
        "count": len(edges),
    }


def extract_edges_from_text(text: str, source_ref: str = "") -> list[dict[str, Any]]:
    """Extrai conceitos de tags ou palavras-chave e liga ao centro."""
    tags = re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text.lower())
    tags = list(dict.fromkeys(tags))[:8]
    if len(tags) < 2:
        return []
    center = tags[0]
    return [add_edge(center, t, "co_occurs", 0.5, source_ref) for t in tags[1:]]


def graph_stats() -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(memory_status, 'active') AS status, COUNT(*) AS count
            FROM knowledge_edges
            GROUP BY COALESCE(memory_status, 'active')
            """
        ).fetchall()
    by_status = {str(row["status"]): int(row["count"] or 0) for row in rows}
    return {"edges": sum(by_status.values()), "by_status": by_status, "active_edges": by_status.get("active", 0)}
