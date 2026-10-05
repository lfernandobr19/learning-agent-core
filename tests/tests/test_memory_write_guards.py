from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

import pytest

from learning_agent.core import errors, graph, knowledge, proofs


@pytest.fixture()
def isolated_memory_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sqlite_path = tmp_path / "learning.db"
    _init_schema(sqlite_path)
    for module in (knowledge, errors, graph, proofs):
        monkeypatch.setattr(module.db, "init_db", lambda: None)
        monkeypatch.setattr(module.db, "get_connection", lambda: _temp_connection(sqlite_path))
    monkeypatch.setattr(proofs, "AUTO_PROOFS", False)
    monkeypatch.setattr("learning_agent.rag.index_document", lambda *args, **kwargs: None)
    monkeypatch.setattr("learning_agent.rag.search_knowledge", lambda *args, **kwargs: [])
    return sqlite_path


def test_add_note_skips_exact_duplicate(isolated_memory_writes: Path) -> None:
    first = knowledge.add_note("Same title", "Same content", tags=["memory"], sync_cloud=False)
    second = knowledge.add_note("Same title", "Same content", tags=["memory"], sync_cloud=False)

    assert first["note_id"] == second["note_id"]
    assert second["duplicate_skipped"] is True
    assert _count(isolated_memory_writes, "learning_notes") == 1
    assert _occurrences(isolated_memory_writes, "learning_notes") == 2


def test_record_failure_skips_exact_duplicate(isolated_memory_writes: Path) -> None:
    first = errors.record_failure("ctx", "boom", "fix", tags=["memory"], sync_cloud=False)
    second = errors.record_failure("ctx", "boom", "fix", tags=["memory"], sync_cloud=False)

    assert first["error_id"] == second["error_id"]
    assert second["duplicate_skipped"] is True
    assert _count(isolated_memory_writes, "learning_errors") == 1
    assert _occurrences(isolated_memory_writes, "learning_errors") == 2


def test_add_edge_skips_duplicate_and_keeps_max_weight(isolated_memory_writes: Path) -> None:
    first = graph.add_edge("Python", "FastAPI", "uses", 0.3, "test")
    second = graph.add_edge("Python", "FastAPI", "uses", 0.9, "test")

    assert first["edge_id"] == second["edge_id"]
    assert second["duplicate_skipped"] is True
    assert _count(isolated_memory_writes, "knowledge_edges") == 1
    with sqlite3.connect(isolated_memory_writes) as conn:
        assert conn.execute("SELECT weight FROM knowledge_edges").fetchone()[0] == 0.9
    assert _occurrences(isolated_memory_writes, "knowledge_edges") == 2


@contextmanager
def _temp_connection(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _occurrences(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(f"SELECT occurrence_count FROM {table}").fetchone()[0])


def _init_schema(path: Path) -> None:
    with sqlite3.connect(path) as conn:
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
