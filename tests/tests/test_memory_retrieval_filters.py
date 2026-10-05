from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pytest

from learning_agent.core import errors, graph, knowledge


@pytest.fixture()
def isolated_retrieval_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sqlite_path = tmp_path / "learning.db"
    with sqlite3.connect(sqlite_path) as conn:
        conn.executescript(
            """
            CREATE TABLE learning_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                memory_status TEXT DEFAULT 'active',
                canonical_id INTEGER,
                superseded_at TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE learning_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context TEXT NOT NULL,
                error TEXT NOT NULL,
                fix TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                memory_status TEXT DEFAULT 'active',
                canonical_id INTEGER,
                superseded_at TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE knowledge_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_concept TEXT NOT NULL,
                to_concept TEXT NOT NULL,
                relation TEXT DEFAULT 'relates_to',
                weight REAL DEFAULT 1.0,
                source_ref TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                memory_status TEXT DEFAULT 'active',
                canonical_id INTEGER,
                superseded_at TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            "INSERT INTO learning_notes (title, content, tags, created_at, updated_at, memory_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("Active", "use me", "[]", "now", "now", "active"),
        )
        conn.execute(
            "INSERT INTO learning_notes (title, content, tags, created_at, updated_at, memory_status, canonical_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("Old", "skip me", "[]", "now", "now", "superseded", 1),
        )
        conn.execute(
            "INSERT INTO learning_errors (context, error, fix, tags, created_at, memory_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("ctx", "active error", "fix", "[]", "now", "active"),
        )
        conn.execute(
            "INSERT INTO learning_errors (context, error, fix, tags, created_at, memory_status, canonical_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("ctx", "old error", "fix", "[]", "now", "superseded", 1),
        )
        conn.execute(
            "INSERT INTO knowledge_edges (from_concept, to_concept, relation, weight, source_ref, created_at, memory_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("python", "testing", "rel", 0.9, "src", "now", "active"),
        )
        conn.execute(
            "INSERT INTO knowledge_edges (from_concept, to_concept, relation, weight, source_ref, created_at, memory_status, canonical_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("python", "old", "rel", 0.9, "src", "now", "superseded", 1),
        )

    for module in (knowledge, errors, graph):
        monkeypatch.setattr(module.db, "init_db", lambda: None)
        monkeypatch.setattr(module.db, "get_connection", lambda: _temp_connection(sqlite_path))
    def fake_search(query: str, limit: int = 5):
        if query == "errors":
            return [
            {"id": "error:2", "content": "old error", "metadata": {"type": "learning_error", "error_id": "2"}, "distance": 0.1},
            {"id": "error:1", "content": "active error", "metadata": {"type": "learning_error", "error_id": "1"}, "distance": 0.2},
            ]
        return [
            {"id": "note:2", "content": "skip me", "metadata": {}, "distance": 0.1},
            {"id": "note:1", "content": "use me", "metadata": {}, "distance": 0.2},
            {"id": "doc:external", "content": "external", "metadata": {}, "distance": 0.3},
        ]

    monkeypatch.setattr(knowledge.rag, "search_knowledge", fake_search)
    return sqlite_path


def test_search_filters_superseded_memory(isolated_retrieval_db: Path) -> None:
    results = knowledge.search("anything", limit=5)

    assert [item["id"] for item in results] == ["note:1", "doc:external"]
    assert results[0]["metadata"]["memory_status"] == "active"


def test_related_errors_filter_superseded_memory(isolated_retrieval_db: Path) -> None:
    results = errors.get_related_errors("errors", limit=5)

    assert [item["id"] for item in results] == [1]


def test_related_concepts_filter_superseded_edges(isolated_retrieval_db: Path) -> None:
    results = graph.get_related_concepts("python", depth=1, limit=5)

    assert [edge["to_concept"] for edge in results["edges"]] == ["testing"]


@contextmanager
def _temp_connection(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
