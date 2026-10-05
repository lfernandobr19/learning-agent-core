from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import sqlite3

import pytest

from learning_agent.core import memory_audit


@pytest.fixture()
def isolated_memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sqlite_path = tmp_path / "learning.db"
    _init_memory_schema(sqlite_path)
    monkeypatch.setattr(memory_audit.db, "init_db", lambda: None)
    monkeypatch.setattr(memory_audit.db, "get_connection", lambda: _temp_connection(sqlite_path))
    monkeypatch.setattr("learning_agent.rag.get_collection", lambda: _FakeCollection(0))
    return sqlite_path


class _FakeCollection:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


def test_memory_audit_detects_duplicates_without_mutating(isolated_memory_db: Path) -> None:
    with sqlite3.connect(isolated_memory_db) as conn:
        conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("Repeated lesson", "same", '["audit"]', "now", "now"))
        conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("Repeated lesson", "same again", '["audit"]', "now", "now"))
        conn.execute("INSERT INTO learning_errors (context, error, fix, tags, created_at) VALUES (?, ?, ?, ?, ?)", ("ctx", "same error", "", '["audit"]', "now"))
        conn.execute("INSERT INTO learning_errors (context, error, fix, tags, created_at) VALUES (?, ?, ?, ?, ?)", ("ctx", "same error", "", '["audit"]', "now"))

    before = _counts(isolated_memory_db)
    report = memory_audit.run_memory_audit(limit=5)
    after = _counts(isolated_memory_db)

    assert before == after
    assert report["dry_run"] is True
    assert report["safety"]["deletes_data"] is False
    assert report["duplicate_note_titles"][0]["title"] == "Repeated lesson"
    assert report["duplicate_note_titles"][0]["count"] == 2
    assert report["duplicate_errors"][0]["error"] == "same error"
    assert report["duplicate_errors"][0]["count"] == 2


def test_memory_curation_dry_run_and_apply_supersedes_duplicates(isolated_memory_db: Path) -> None:
    with sqlite3.connect(isolated_memory_db) as conn:
        conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("Canonical note", "same", '["audit"]', "now", "now"))
        conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", ("Canonical note", "same", '["audit"]', "now", "now"))
        conn.execute("INSERT INTO learning_errors (context, error, fix, tags, created_at) VALUES (?, ?, ?, ?, ?)", ("ctx", "same", "fix", '["audit"]', "now"))
        conn.execute("INSERT INTO learning_errors (context, error, fix, tags, created_at) VALUES (?, ?, ?, ?, ?)", ("ctx", "same", "fix", '["audit"]', "now"))
        conn.execute("INSERT INTO knowledge_edges (from_concept, to_concept, relation, weight, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("a", "b", "rel", 1.0, "src", "now"))
        conn.execute("INSERT INTO knowledge_edges (from_concept, to_concept, relation, weight, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)", ("a", "b", "rel", 0.5, "src", "now"))

    dry_run = memory_audit.run_memory_curation(limit=5)
    assert dry_run["dry_run"] is True
    assert dry_run["total_candidate_duplicates"] == 3
    assert _superseded_count(isolated_memory_db, "learning_notes") == 0

    applied = memory_audit.run_memory_curation(apply=True, limit=5)
    assert applied["dry_run"] is False
    assert applied["total_marked_superseded"] == 3
    assert _superseded_count(isolated_memory_db, "learning_notes") == 1
    assert _superseded_count(isolated_memory_db, "learning_errors") == 1
    assert _superseded_count(isolated_memory_db, "knowledge_edges") == 1

    restored = memory_audit.restore_superseded_memory(limit=10)
    assert restored["total_restored"] == 3
    assert _superseded_count(isolated_memory_db, "learning_notes") == 0


def test_memory_curation_can_process_multiple_batches(isolated_memory_db: Path) -> None:
    with sqlite3.connect(isolated_memory_db) as conn:
        for title in ("A", "B", "C"):
            conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (title, "same", "[]", "now", "now"))
            conn.execute("INSERT INTO learning_notes (title, content, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (title, "same", "[]", "now", "now"))

    applied = memory_audit.run_memory_curation(
        apply=True,
        limit=1,
        max_batches=10,
        include_groups=False,
    )

    assert applied["total_marked_superseded"] == 3
    assert applied["tables"][0]["groups"] == []
    assert _superseded_count(isolated_memory_db, "learning_notes") == 3


@contextmanager
def _temp_connection(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            "learning_notes": conn.execute("SELECT COUNT(*) FROM learning_notes").fetchone()[0],
            "learning_errors": conn.execute("SELECT COUNT(*) FROM learning_errors").fetchone()[0],
        }


def _superseded_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE memory_status = 'superseded'"
            ).fetchone()[0]
        )


def _init_memory_schema(path: Path) -> None:
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
            CREATE TABLE agent_insights (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE agent_exchanges (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE quiz_items (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE quiz_attempts (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE study_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE distillation_pairs (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT);
            CREATE TABLE chat_conversations (id TEXT PRIMARY KEY);
            """
        )
