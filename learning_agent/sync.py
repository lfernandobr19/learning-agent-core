import json
import time
from typing import Any

import httpx

from learning_agent import db
from learning_agent import rag
from learning_agent.config import (
    AUTO_SYNC,
    AUTO_SYNC_DEBOUNCE_SECONDS,
    CLOUD_SYNC_ENABLED,
    SUPABASE_KEY,
    SUPABASE_URL,
)
from learning_agent.core import progress as progress_core

_last_auto_push: float = 0.0


def is_configured() -> bool:
    return CLOUD_SYNC_ENABLED and bool(SUPABASE_URL and SUPABASE_KEY)


def _headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }


def export_snapshot() -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        notes = db.rows_to_list(conn.execute("SELECT * FROM learning_notes").fetchall())
        quizzes = db.rows_to_list(conn.execute("SELECT * FROM quiz_items").fetchall())
        attempts = db.rows_to_list(conn.execute("SELECT * FROM quiz_attempts").fetchall())
        sessions = db.rows_to_list(conn.execute("SELECT * FROM study_sessions").fetchall())
        agent_sessions = db.rows_to_list(conn.execute("SELECT * FROM agent_sessions").fetchall())
        learning_errors = db.rows_to_list(conn.execute("SELECT * FROM learning_errors").fetchall())
        distillation_pairs = db.rows_to_list(conn.execute("SELECT * FROM distillation_pairs").fetchall())
        knowledge_edges = db.rows_to_list(conn.execute("SELECT * FROM knowledge_edges").fetchall())
        learning_queue = db.rows_to_list(conn.execute("SELECT * FROM learning_queue").fetchall())
        chat_messages = db.rows_to_list(
            conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT 500"
            ).fetchall()
        )
        try:
            chat_conversations = db.rows_to_list(
                conn.execute("SELECT * FROM chat_conversations ORDER BY updated_at DESC").fetchall()
            )
        except Exception:
            chat_conversations = []

    return {
        "version": 4,
        "notes": notes,
        "quiz_items": quizzes,
        "quiz_attempts": attempts,
        "study_sessions": sessions,
        "agent_sessions": agent_sessions,
        "learning_errors": learning_errors,
        "distillation_pairs": distillation_pairs,
        "knowledge_edges": knowledge_edges,
        "learning_queue": learning_queue,
        "chat_messages": chat_messages,
        "chat_conversations": chat_conversations,
        "knowledge": rag.list_all_documents(),
        "progress": progress_core.get_progress(),
    }


def test_connection() -> dict[str, Any]:
    if not is_configured():
        return {"success": False, "message": "Configure SUPABASE_URL e SUPABASE_KEY no .env"}

    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            f"{SUPABASE_URL}/rest/v1/learning_snapshots?select=id&limit=1",
            headers=_headers(),
        )
        if response.status_code == 404 or "learning_snapshots" in response.text:
            return {
                "success": False,
                "message": "Tabela learning_snapshots não existe. Rode integrations/supabase-schema.sql no SQL Editor.",
            }
        if response.status_code >= 400:
            return {
                "success": False,
                "message": f"Erro Supabase: {response.status_code} {response.text}",
            }

    return {"success": True, "message": "Conexão com Supabase OK"}


def push_to_cloud() -> dict[str, Any]:
    if not is_configured():
        return {
            "success": False,
            "message": "Cloud sync not configured. Set SUPABASE_URL and SUPABASE_KEY in .env",
        }

    conn_test = test_connection()
    if not conn_test["success"]:
        return conn_test

    snapshot = export_snapshot()
    now = db._utcnow()
    payload = {"id": "default", "data": snapshot, "updated_at": now}

    with httpx.Client(timeout=120.0) as client:
        # Upsert: PATCH se já existe, POST se é o primeiro envio
        check = client.get(
            f"{SUPABASE_URL}/rest/v1/learning_snapshots?id=eq.default&select=id",
            headers=_headers(),
        )
        if check.status_code >= 400:
            return {
                "success": False,
                "message": f"Supabase error: {check.status_code} {check.text}",
            }

        if check.json():
            response = client.patch(
                f"{SUPABASE_URL}/rest/v1/learning_snapshots?id=eq.default",
                headers=_headers(),
                content=json.dumps({"data": snapshot, "updated_at": now}),
            )
        else:
            response = client.post(
                f"{SUPABASE_URL}/rest/v1/learning_snapshots",
                headers=_headers(),
                content=json.dumps(payload),
            )

        if response.status_code >= 400:
            return {
                "success": False,
                "message": f"Supabase error: {response.status_code} {response.text}",
            }

    return {
        "success": True,
        "message": "Snapshot pushed to cloud",
        "notes": len(snapshot["notes"]),
        "knowledge_docs": len(snapshot.get("knowledge", [])),
        "updated_at": now,
    }


def pull_from_cloud() -> dict[str, Any]:
    if not is_configured():
        return {
            "success": False,
            "message": "Cloud sync not configured. Set SUPABASE_URL and SUPABASE_KEY in .env",
        }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{SUPABASE_URL}/rest/v1/learning_snapshots?id=eq.default&select=data",
            headers=_headers(),
        )
        if response.status_code >= 400:
            return {
                "success": False,
                "message": f"Supabase error: {response.status_code} {response.text}",
            }

        rows = response.json()
        if not rows:
            return {"success": False, "message": "No snapshot found in cloud"}

        snapshot = rows[0]["data"]

    db.init_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM quiz_attempts")
        conn.execute("DELETE FROM quiz_items")
        conn.execute("DELETE FROM learning_notes")
        conn.execute("DELETE FROM study_sessions")
        conn.execute("DELETE FROM agent_sessions")
        conn.execute("DELETE FROM learning_errors")
        conn.execute("DELETE FROM distillation_pairs")
        conn.execute("DELETE FROM knowledge_edges")
        conn.execute("DELETE FROM learning_queue")
        conn.execute("DELETE FROM chat_messages")

        for note in snapshot.get("notes", []):
            conn.execute(
                """
                INSERT INTO learning_notes (id, title, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    note["id"],
                    note["title"],
                    note["content"],
                    note.get("tags", "[]"),
                    note["created_at"],
                    note.get("updated_at", note["created_at"]),
                ),
            )

        for item in snapshot.get("quiz_items", []):
            conn.execute(
                """
                INSERT INTO quiz_items
                (id, topic, question, answer, difficulty, ease_factor, interval_days,
                 repetitions, next_review, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["topic"],
                    item["question"],
                    item["answer"],
                    item.get("difficulty", "medium"),
                    item.get("ease_factor", 2.5),
                    item.get("interval_days", 1),
                    item.get("repetitions", 0),
                    item.get("next_review"),
                    item["created_at"],
                ),
            )

        for attempt in snapshot.get("quiz_attempts", []):
            conn.execute(
                """
                INSERT INTO quiz_attempts (id, quiz_item_id, correct, response, attempted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    attempt["id"],
                    attempt["quiz_item_id"],
                    attempt["correct"],
                    attempt.get("response", ""),
                    attempt["attempted_at"],
                ),
            )

        for session in snapshot.get("study_sessions", []):
            conn.execute(
                """
                INSERT INTO study_sessions (id, topic, duration_minutes, notes, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    session["topic"],
                    session.get("duration_minutes", 0),
                    session.get("notes"),
                    session["started_at"],
                ),
            )

        for agent_session in snapshot.get("agent_sessions", []):
            conn.execute(
                """
                INSERT INTO agent_sessions (id, summary, topics, decisions, duration_minutes, started_at, ended_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_session["id"],
                    agent_session["summary"],
                    agent_session.get("topics", "[]"),
                    agent_session.get("decisions", "[]"),
                    agent_session.get("duration_minutes", 0),
                    agent_session["started_at"],
                    agent_session.get("ended_at"),
                ),
            )

        for err in snapshot.get("learning_errors", []):
            conn.execute(
                """
                INSERT INTO learning_errors (id, context, error, fix, tags, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    err["id"],
                    err["context"],
                    err["error"],
                    err.get("fix", ""),
                    err.get("tags", "[]"),
                    err["created_at"],
                ),
            )

        for pair in snapshot.get("distillation_pairs", []):
            conn.execute(
                """
                INSERT INTO distillation_pairs (
                    id, topic, source_ref, teacher_output, student_output,
                    soft_labels, similarity_score, teacher_model, student_model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pair["id"],
                    pair["topic"],
                    pair.get("source_ref", ""),
                    pair["teacher_output"],
                    pair["student_output"],
                    pair.get("soft_labels", "{}"),
                    pair.get("similarity_score", 0),
                    pair.get("teacher_model"),
                    pair.get("student_model"),
                    pair["created_at"],
                ),
            )

        for edge in snapshot.get("knowledge_edges", []):
            conn.execute(
                """
                INSERT INTO knowledge_edges (id, from_concept, to_concept, relation, weight, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge["id"],
                    edge["from_concept"],
                    edge["to_concept"],
                    edge.get("relation", "relates_to"),
                    edge.get("weight", 1.0),
                    edge.get("source_ref", ""),
                    edge["created_at"],
                ),
            )

        for item in snapshot.get("learning_queue", []):
            conn.execute(
                """
                INSERT INTO learning_queue (id, topic, reason, status, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["topic"],
                    item.get("reason", ""),
                    item.get("status", "pending"),
                    item["created_at"],
                    item.get("completed_at"),
                ),
            )

        for msg in snapshot.get("chat_messages", []):
            conn.execute(
                """
                INSERT INTO chat_messages (id, channel, user_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    msg["id"],
                    msg["channel"],
                    msg["user_id"],
                    msg["role"],
                    msg["content"],
                    msg["created_at"],
                ),
            )

    for doc in snapshot.get("knowledge", []):
        rag.index_document(doc["id"], doc["content"], doc.get("metadata"))

    return {
        "success": True,
        "message": "Snapshot restored from cloud",
        "notes": len(snapshot.get("notes", [])),
    }


def maybe_auto_push(force: bool = False) -> dict[str, Any] | None:
    """Push to Supabase automatically if AUTO_SYNC is enabled."""
    global _last_auto_push

    if not is_configured() or not AUTO_SYNC:
        return None

    now = time.monotonic()
    if not force and (now - _last_auto_push) < AUTO_SYNC_DEBOUNCE_SECONDS:
        return {
            "success": True,
            "message": "Sync recente — debounce ativo",
            "skipped": True,
        }

    result = push_to_cloud()
    if result.get("success"):
        _last_auto_push = now
    return result


def attach_cloud_sync(result: dict[str, Any], force: bool = False) -> dict[str, Any]:
    """Attach cloud_sync field to a tool/API result after auto-push."""
    try:
        sync_result = maybe_auto_push(force=force)
        if sync_result is not None:
            result["cloud_sync"] = sync_result
    except Exception as exc:
        result["cloud_sync"] = {"success": False, "message": str(exc)[:200], "skipped": True}
    return result


def push_conversations_to_cloud() -> dict[str, Any]:
    """Upsert conversas + mensagens recentes nas tabelas first-class do Supabase."""
    if not is_configured():
        return {"success": False, "message": "Cloud sync not configured"}

    db.init_db()
    with db.get_connection() as conn:
        try:
            conversations = db.rows_to_list(
                conn.execute("SELECT * FROM chat_conversations").fetchall()
            )
        except Exception as exc:
            return {"success": False, "message": f"local conversations: {exc}"}
        messages = db.rows_to_list(
            conn.execute(
                "SELECT * FROM chat_messages ORDER BY id DESC LIMIT 2000"
            ).fetchall()
        )

    conv_rows: list[dict[str, Any]] = []
    for c in conversations:
        conv_rows.append(
            {
                "id": c["id"],
                "channel": c.get("channel") or "ide",
                "title": c.get("title") or "Nova conversa",
                "archived": bool(c.get("archived")),
                "project_name": c.get("project_name") or "",
                "project_root": c.get("project_root") or "",
                "workspace_root_ids": json.loads(c.get("workspace_root_ids") or "[]")
                if isinstance(c.get("workspace_root_ids"), str)
                else (c.get("workspace_root_ids") or []),
                "updated_at": c.get("updated_at") or db._utcnow(),
                "created_at": c.get("created_at") or db._utcnow(),
                "user_id": "default",
            }
        )

    msg_rows: list[dict[str, Any]] = []
    for m in messages:
        mid = f"{m.get('channel')}:{m.get('user_id')}:{m.get('id')}"
        media = m.get("media_json") or "[]"
        if isinstance(media, str):
            try:
                media = json.loads(media)
            except Exception:
                media = []
        msg_rows.append(
            {
                "id": mid,
                "conversation_id": m.get("user_id"),
                "channel": m.get("channel") or "ide",
                "role": m.get("role") or "user",
                "content": m.get("content") or "",
                "media_json": media,
                "created_at": m.get("created_at") or db._utcnow(),
            }
        )

    # Só mensagens cuja conversa existe
    conv_ids = {c["id"] for c in conv_rows}
    msg_rows = [m for m in msg_rows if m["conversation_id"] in conv_ids]

    with httpx.Client(timeout=60.0) as client:
        if conv_rows:
            r = client.post(
                f"{SUPABASE_URL}/rest/v1/ravenna_conversations",
                headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
                content=json.dumps(conv_rows),
            )
            if r.status_code >= 400:
                return {
                    "success": False,
                    "message": f"conversations upsert: {r.status_code} {r.text[:300]}",
                }
        if msg_rows:
            # chunks
            for i in range(0, len(msg_rows), 200):
                chunk = msg_rows[i : i + 200]
                r = client.post(
                    f"{SUPABASE_URL}/rest/v1/ravenna_chat_messages",
                    headers={**_headers(), "Prefer": "resolution=merge-duplicates"},
                    content=json.dumps(chunk),
                )
                if r.status_code >= 400:
                    return {
                        "success": False,
                        "message": f"messages upsert: {r.status_code} {r.text[:300]}",
                    }

    return {
        "success": True,
        "conversations": len(conv_rows),
        "messages": len(msg_rows),
    }


def pull_conversations_from_cloud() -> dict[str, Any]:
    """Merge conversas da nuvem para SQLite (last-write-wins por updated_at)."""
    if not is_configured():
        return {"success": False, "message": "Cloud sync not configured"}

    with httpx.Client(timeout=60.0) as client:
        cr = client.get(
            f"{SUPABASE_URL}/rest/v1/ravenna_conversations?select=*&order=updated_at.desc",
            headers=_headers(),
        )
        if cr.status_code >= 400:
            return {
                "success": False,
                "message": f"pull conversations: {cr.status_code} {cr.text[:300]}",
            }
        cloud_convs = cr.json() or []
        mr = client.get(
            f"{SUPABASE_URL}/rest/v1/ravenna_chat_messages?select=*&order=created_at.asc&limit=5000",
            headers=_headers(),
        )
        if mr.status_code >= 400:
            return {
                "success": False,
                "message": f"pull messages: {mr.status_code} {mr.text[:300]}",
            }
        cloud_msgs = mr.json() or []

    db.init_db()
    merged_c = 0
    merged_m = 0
    with db.get_connection() as conn:
        for c in cloud_convs:
            local = conn.execute(
                "SELECT updated_at FROM chat_conversations WHERE id = ?",
                (c["id"],),
            ).fetchone()
            remote_u = c.get("updated_at") or ""
            if local and (local["updated_at"] or "") >= remote_u:
                continue
            roots = c.get("workspace_root_ids") or []
            if not isinstance(roots, str):
                roots = json.dumps(roots)
            conn.execute(
                """
                INSERT INTO chat_conversations (
                    id, channel, title, created_at, updated_at, archived,
                    project_name, project_root, workspace_root_ids
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    updated_at=excluded.updated_at,
                    archived=excluded.archived,
                    project_name=excluded.project_name,
                    project_root=excluded.project_root,
                    workspace_root_ids=excluded.workspace_root_ids
                """,
                (
                    c["id"],
                    c.get("channel") or "ide",
                    c.get("title") or "Nova conversa",
                    c.get("created_at") or remote_u,
                    remote_u,
                    1 if c.get("archived") else 0,
                    c.get("project_name") or "",
                    c.get("project_root") or "",
                    roots,
                ),
            )
            merged_c += 1

        for m in cloud_msgs:
            cid = m.get("conversation_id")
            if not cid:
                continue
            content = m.get("content") or ""
            created = m.get("created_at") or ""
            role = m.get("role") or "user"
            channel = m.get("channel") or "ide"
            exists = conn.execute(
                """
                SELECT 1 FROM chat_messages
                WHERE channel = ? AND user_id = ? AND role = ? AND content = ? AND created_at = ?
                LIMIT 1
                """,
                (channel, cid, role, content, created),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO chat_messages (channel, user_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (channel, cid, role, content, created),
            )
            merged_m += 1

    return {
        "success": True,
        "conversations_merged": merged_c,
        "messages_merged": merged_m,
        "cloud_conversations": len(cloud_convs),
        "cloud_messages": len(cloud_msgs),
    }
