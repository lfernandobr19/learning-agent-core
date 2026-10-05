"""Dashboard agregado de progresso — agentes, journal, destilação, IDE."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from learning_agent import db
from learning_agent.core import agent_capability, agent_benchmarks, agent_external_completion, ide_objectives, ship_pipeline

DASHBOARD_AGENTS = [
    *agent_capability.CORE_AGENTS,
    "finance-lead",
    "ravenna-ide-rebuild",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _action_timeline(days: int = 14) -> list[dict[str, Any]]:
    db.init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day,
                   COUNT(*) AS total,
                   SUM(success) AS successes,
                   SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failures
            FROM agent_action_log
            WHERE substr(created_at, 1, 10) >= ?
            GROUP BY day
            ORDER BY day
            """,
            (cutoff,),
        ).fetchall()

    by_day = {r["day"]: dict(r) for r in rows}
    timeline: list[dict[str, Any]] = []
    start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        row = by_day.get(d, {"day": d, "total": 0, "successes": 0, "failures": 0})
        timeline.append(
            {
                "day": d,
                "total": int(row.get("total") or 0),
                "successes": int(row.get("successes") or 0),
                "failures": int(row.get("failures") or 0),
            }
        )
    return timeline


def _action_by_agent() -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT agent,
                   COUNT(*) AS total,
                   SUM(success) AS successes,
                   MAX(created_at) AS last_at
            FROM agent_action_log
            GROUP BY agent
            ORDER BY total DESC
            """
        ).fetchall()
    return [
        {
            "agent": r["agent"],
            "total": int(r["total"] or 0),
            "successes": int(r["successes"] or 0),
            "failures": int(r["total"] or 0) - int(r["successes"] or 0),
            "success_rate": round(100 * int(r["successes"] or 0) / max(int(r["total"] or 1), 1), 1),
            "last_at": r["last_at"],
        }
        for r in rows
    ]


def _recent_actions(limit: int = 25) -> list[dict[str, Any]]:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, agent, action, topic, project, success, summary, error, created_at
            FROM agent_action_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["success"] = bool(item.get("success"))
        item["summary"] = (item.get("summary") or "")[:200]
        item["error"] = (item.get("error") or "")[:120]
        out.append(item)
    return out


def _distillation_stats() -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0])
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
            FROM distillation_pairs
            WHERE substr(created_at, 1, 10) >= date('now', '-13 days')
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
        finance = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM distillation_pairs
                WHERE lower(topic) LIKE '%finance%'
                   OR lower(topic) LIKE '%invest%'
                   OR lower(topic) LIKE '%trading%'
                """
            ).fetchone()[0]
        )
        ide = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM distillation_pairs
                WHERE lower(topic) LIKE '%ide%'
                   OR lower(topic) LIKE '%cursor%'
                   OR lower(topic) LIKE '%vscode%'
                   OR lower(topic) LIKE '%editor%'
                """
            ).fetchone()[0]
        )

    timeline = [{"day": r["day"], "count": int(r["count"])} for r in rows]
    return {
        "total": total,
        "finance_topics": finance,
        "ide_topics": ide,
        "other_topics": max(total - finance - ide, 0),
        "timeline": timeline,
    }


def build_progress_dashboard(*, days: int = 14) -> dict[str, Any]:
    """Agrega evolução, journal, destilação e paridade IDE."""
    db.init_db()

    agents = [agent_capability.compute_agent_capability(name) for name in DASHBOARD_AGENTS]
    agents.sort(key=lambda x: (-x["level"], -x["score"]))

    level_counts = {i: 0 for i in range(1, 7)}
    for a in agents:
        level_counts[a["level"]] = level_counts.get(a["level"], 0) + 1

    specialists_l5 = sum(1 for a in agents if a["level"] >= 5)
    specialists_l6 = sum(1 for a in agents if a["level"] >= 6)

    ide = ide_objectives.assess_completion(run_slow_probes=False)
    ide_summary = ide.get("summary") or {}

    action_timeline = _action_timeline(days=days)
    action_total = sum(d["total"] for d in action_timeline)
    action_success = sum(d["successes"] for d in action_timeline)

    with db.get_connection() as conn:
        journal_total = int(conn.execute("SELECT COUNT(*) FROM agent_action_log").fetchone()[0])

    external = agent_external_completion.assess_external_completion("finance-lead")
    ship = ship_pipeline.build_ship_status()
    blind = agent_benchmarks.benchmark_summary("finance-lead")
    velocity = ship.get("velocity") or {}

    return {
        "success": True,
        "generated_at": _utcnow(),
        "operating_mode": ship_pipeline.load_operating_mode(),
        "summary": {
            "agents_total": len(agents),
            "specialists_l5": specialists_l5,
            "specialists_l6": specialists_l6,
            "level_counts": level_counts,
            "journal_total": journal_total,
            "actions_last_days": action_total,
            "action_success_rate": round(100 * action_success / max(action_total, 1), 1),
            "ide_parity_pct": ide_summary.get("cursor_parity_pct", 0),
            "ide_must_met": ide_summary.get("must_met", 0),
            "ide_must_total": ide_summary.get("must_total", 0),
            "distillation_pairs": _distillation_stats()["total"],
            "external_pass_count": external.get("passed_count", 0),
            "external_pass_total": external.get("total", 5),
            "external_ready": external.get("external_ready", False),
            "ship_merges_14d": velocity.get("merges", 0),
            "train_to_ship_ratio": velocity.get("train_to_ship_ratio", 0),
            "ship_alert": velocity.get("alert", False),
            "blind_score": blind.get("latest_composite", 0),
        },
        "external_completion": external,
        "ship": {
            "queue_ready": ship.get("queue_ready", 0),
            "next_item": ship.get("next_item"),
            "velocity": velocity,
            "done_recent": ship.get("done_recent", [])[:5],
        },
        "benchmarks": blind,
        "agents": agents,
        "action_timeline": action_timeline,
        "action_by_agent": _action_by_agent(),
        "recent_actions": _recent_actions(),
        "distillation": _distillation_stats(),
        "ide_completion": {
            "complete": ide.get("complete", False),
            "north_star": ide.get("north_star", ""),
            "summary": ide_summary,
            "missing_must": ide.get("missing_must", [])[:8],
        },
    }
