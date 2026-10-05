import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from learning_agent.config import SQLITE_PATH

T = TypeVar("T")
SQLITE_BUSY_TIMEOUT_MS = 30000
DB_RETRY_ATTEMPTS = 5


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS learning_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                difficulty TEXT DEFAULT 'medium',
                ease_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 1,
                repetitions INTEGER DEFAULT 0,
                next_review TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_item_id INTEGER NOT NULL,
                correct INTEGER NOT NULL,
                response TEXT,
                attempted_at TEXT NOT NULL,
                FOREIGN KEY (quiz_item_id) REFERENCES quiz_items(id)
            );

            CREATE TABLE IF NOT EXISTS study_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                duration_minutes INTEGER DEFAULT 0,
                notes TEXT,
                started_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS distillation_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                source_ref TEXT DEFAULT '',
                teacher_output TEXT NOT NULL,
                student_output TEXT NOT NULL,
                soft_labels TEXT DEFAULT '{}',
                similarity_score REAL DEFAULT 0,
                teacher_model TEXT,
                student_model TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                topics TEXT DEFAULT '[]',
                decisions TEXT DEFAULT '[]',
                duration_minutes INTEGER DEFAULT 0,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );

            CREATE TABLE IF NOT EXISTS learning_errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context TEXT NOT NULL,
                error TEXT NOT NULL,
                fix TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_concept TEXT NOT NULL,
                to_concept TEXT NOT NULL,
                relation TEXT DEFAULT 'relates_to',
                weight REAL DEFAULT 1.0,
                source_ref TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS learning_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                reason TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_conversations (
                id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chat_plans (
                conversation_id TEXT PRIMARY KEY,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chat_messages_user
                ON chat_messages(channel, user_id, id);

            CREATE TABLE IF NOT EXISTS agent_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL DEFAULT 'cursor_subagent',
                role TEXT DEFAULT '',
                description TEXT DEFAULT '',
                file_path TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                parent_agent TEXT DEFAULT 'ravenna',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent TEXT NOT NULL,
                to_agents TEXT DEFAULT '[]',
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                note_id INTEGER,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_exchanges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT DEFAULT '',
                message TEXT NOT NULL,
                exchange_type TEXT DEFAULT 'dialogue',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_notes_created ON learning_notes(created_at);
            CREATE INDEX IF NOT EXISTS idx_notes_tags ON learning_notes(tags);
            CREATE INDEX IF NOT EXISTS idx_quiz_items_topic ON quiz_items(topic);
            CREATE INDEX IF NOT EXISTS idx_quiz_attempts_item ON quiz_attempts(quiz_item_id);
            CREATE INDEX IF NOT EXISTS idx_agent_exchanges_thread ON agent_exchanges(thread_id);
            CREATE INDEX IF NOT EXISTS idx_agent_exchanges_from ON agent_exchanges(from_agent);
            CREATE INDEX IF NOT EXISTS idx_agent_insights_from ON agent_insights(from_agent);

            CREATE TABLE IF NOT EXISTS agent_action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                action TEXT NOT NULL,
                topic TEXT DEFAULT '',
                project TEXT DEFAULT '',
                success INTEGER NOT NULL DEFAULT 1,
                summary TEXT DEFAULT '',
                error TEXT DEFAULT '',
                fix TEXT DEFAULT '',
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_agent_action_agent ON agent_action_log(agent);
            CREATE INDEX IF NOT EXISTS idx_agent_action_project ON agent_action_log(project);
            """
        )
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(chat_conversations)").fetchall()
        }
        if "archived" not in cols:
            conn.execute(
                "ALTER TABLE chat_conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
            )
        if "project_name" not in cols:
            conn.execute(
                "ALTER TABLE chat_conversations ADD COLUMN project_name TEXT DEFAULT ''"
            )
        if "project_root" not in cols:
            conn.execute(
                "ALTER TABLE chat_conversations ADD COLUMN project_root TEXT DEFAULT ''"
            )
        if "workspace_root_ids" not in cols:
            conn.execute(
                "ALTER TABLE chat_conversations ADD COLUMN workspace_root_ids TEXT DEFAULT '[]'"
            )
        msg_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()
        }
        if "media_json" not in msg_cols:
            conn.execute("ALTER TABLE chat_messages ADD COLUMN media_json TEXT DEFAULT '[]'")
        for table in ("learning_notes", "learning_errors", "knowledge_edges"):
            table_cols = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if "memory_status" not in table_cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN memory_status TEXT DEFAULT 'active'"
                )
            if "canonical_id" not in table_cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN canonical_id INTEGER"
                )
            if "superseded_at" not in table_cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN superseded_at TEXT"
                )
            if "occurrence_count" not in table_cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1"
                )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_notes_memory_identity
                ON learning_notes(memory_status, title, content, id);
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_learning_errors_memory_identity
                ON learning_errors(memory_status, context, error, fix, id);
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_knowledge_edges_memory_identity
                ON knowledge_edges(memory_status, from_concept, to_concept, relation, source_ref, id);
            """
        )


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


def run_db_retry(fn: Callable[[], T], *, attempts: int = DB_RETRY_ATTEMPTS) -> T:
    """Retry SQLite operations when database is locked."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower() or attempt >= attempts - 1:
                raise
            time.sleep(min(2.0 ** attempt, 8.0))
    if last_exc:
        raise last_exc
    raise RuntimeError("run_db_retry failed without exception")


@contextmanager
def get_connection():
    conn = sqlite3.connect(str(SQLITE_PATH), timeout=SQLITE_BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    _configure_connection(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def parse_tags(tags_json: str) -> list[str]:
    try:
        tags = json.loads(tags_json)
        return tags if isinstance(tags, list) else []
    except json.JSONDecodeError:
        return []


def dump_tags(tags: list[str]) -> str:
    return json.dumps(tags)


def save_chat_plan(conversation_id: str, plan: dict[str, Any]) -> bool:
    """Persist an AgentPlan JSON keyed by conversation. Returns True on upsert."""
    if not conversation_id:
        return False
    now = _utcnow()
    payload = json.dumps(plan, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_plans (conversation_id, plan_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(conversation_id)
            DO UPDATE SET plan_json = excluded.plan_json, updated_at = excluded.updated_at
            """,
            (conversation_id, payload, now, now),
        )
    return True


def load_chat_plan(conversation_id: str) -> dict[str, Any] | None:
    """Load a persisted AgentPlan JSON for a conversation, or None."""
    if not conversation_id:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT plan_json FROM chat_plans WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["plan_json"])
    except (json.JSONDecodeError, TypeError):
        return None


def delete_chat_plan(conversation_id: str) -> bool:
    if not conversation_id:
        return False
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM chat_plans WHERE conversation_id = ?",
            (conversation_id,),
        )
    return True
