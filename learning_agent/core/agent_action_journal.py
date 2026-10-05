"""Journal de ações dos agentes — cada ação e erro vira aprendizado persistente."""

from __future__ import annotations

import json
from typing import Any

from learning_agent import db
from learning_agent.core import agent_collaboration, agent_learning_loop, errors, knowledge, sessions


def log_action(
    agent: str,
    action: str,
    *,
    topic: str = "",
    project: str = "",
    success: bool = True,
    summary: str = "",
    error: str = "",
    fix: str = "",
    meta: dict[str, Any] | None = None,
    sync_note: bool = True,
) -> dict[str, Any]:
    """Registra ação no SQLite + nota RAG (+ falha se houver)."""
    db.init_db()
    slug = agent.strip().lower().replace("_", "-")
    now = db._utcnow()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)

    with db.get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO agent_action_log
            (agent, action, topic, project, success, summary, error, fix, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                action,
                topic[:500],
                project[:120],
                1 if success else 0,
                summary[:4000],
                error[:2000],
                fix[:2000],
                meta_json,
                now,
            ),
        )
        action_id = int(cur.lastrowid)

    tags = ["agent-action", f"agent:{slug}", action]
    if project:
        tags.append(f"project:{project}")

    note_body = (
        f"**Ação:** `{action}`\n"
        f"**Projeto:** {project or '—'}\n"
        f"**Tópico:** {topic or '—'}\n"
        f"**Sucesso:** {'sim' if success else 'não'}\n\n"
        f"### Resumo\n{summary[:2500] or '—'}\n"
    )
    if error:
        note_body += f"\n### Erro\n{error}\n\n### Correção\n{fix or '(pendente)'}\n"

    note = None
    if sync_note:
        manifest = agent_collaboration._load_manifest(slug) or {}
        prefix = manifest.get("learning", {}).get("note_prefix", f"Agente {slug}")
        note = knowledge.add_note(
            f"[Ação] {prefix} — {action}",
            note_body,
            tags=tags,
            sync_cloud=False,
        )

    failure_row = None
    if error:
        failure_row = errors.record_failure(
            context=f"{slug}/{action}/{topic[:80]}",
            error=error,
            fix=fix,
            tags=tags + ["action-failure"],
            sync_cloud=False,
        )

    if success and summary:
        agent_collaboration.share_insight(
            slug,
            summary[:400],
            topic or action,
            to_agents=["all"],
        )

    return {
        "success": True,
        "action_id": action_id,
        "agent": slug,
        "action": action,
        "note_id": note.get("note_id") if note else None,
        "failure_id": failure_row.get("error_id") if failure_row else None,
    }


def complete_action_cycle(
    agent: str,
    action: str,
    topic: str,
    result: dict[str, Any],
    *,
    project: str = "",
    run_closure: bool = True,
    record_session_summary: bool = True,
) -> dict[str, Any]:
    """Fecha ciclo: journal → closure → sessão (qualidade > velocidade)."""
    slug = agent.strip().lower().replace("_", "-")
    ok = result.get("success") is not False
    err = str(result.get("error") or result.get("message") or "")
    if not ok and not err:
        err = json.dumps({k: result[k] for k in result if k in ("error", "message", "hint")}, ensure_ascii=False)[:500]

    summary_parts = [
        str(result.get("plan") or ""),
        str(result.get("proposal") or ""),
        str(result.get("topic") or ""),
        str(result.get("answer") or ""),
    ]
    summary = "\n".join(p for p in summary_parts if p.strip())[:3000] or action

    journal = log_action(
        slug,
        action,
        topic=topic,
        project=project,
        success=ok,
        summary=summary,
        error=err if not ok else "",
        fix=str(result.get("fix") or result.get("hint") or ""),
        meta={"result_keys": list(result.keys())[:20]},
    )

    closure = None
    if run_closure:
        try:
            closure = agent_learning_loop.run_learning_closure(
                action,
                topic,
                result,
                agent=slug,
                broadcast_observer=False,
            )
        except Exception as exc:
            log_action(
                slug,
                "learning_closure",
                topic=topic,
                project=project,
                success=False,
                summary="",
                error=str(exc)[:500],
            )

    session_row = None
    if record_session_summary and ok:
        session_row = sessions.record_session(
            summary=f"[{project or 'treino'}] {action}: {summary[:400]}",
            topics=[topic] if topic else [action],
            decisions=[f"success={ok}"],
        )

    return {
        "success": ok,
        "journal": journal,
        "closure": closure,
        "session": session_row,
    }
