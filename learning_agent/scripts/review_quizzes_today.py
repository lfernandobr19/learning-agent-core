#!/usr/bin/env python3
"""Revisa quizzes criados hoje e tentativas registradas."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent import db  # noqa: E402
from learning_agent.core import progress  # noqa: E402

TODAY_PREFIX = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, question, answer, created_at, next_review, repetitions
            FROM quiz_items
            WHERE created_at LIKE ?
            ORDER BY id
            """,
            (f"{TODAY_PREFIX}%",),
        ).fetchall()

        attempts = conn.execute(
            """
            SELECT qa.quiz_item_id, qa.correct, qa.response, qa.attempted_at, qi.topic
            FROM quiz_attempts qa
            JOIN quiz_items qi ON qi.id = qa.quiz_item_id
            WHERE qa.attempted_at LIKE ?
            """,
            (f"{TODAY_PREFIX}%",),
        ).fetchall()

    by_prefix: dict[str, list] = defaultdict(list)
    for r in rows:
        d = dict(r)
        prefix = d["topic"].split("—")[0].strip() if "—" in d["topic"] else d["topic"].split("-")[0].strip()
        by_prefix[prefix].append(d)

    attempted_ids = {a["quiz_item_id"] for a in attempts}
    unanswered = [dict(r) for r in rows if r["id"] not in attempted_ids]

    prog = progress.get_progress()

    out = {
        "date": TODAY_PREFIX,
        "total_created_today": len(rows),
        "total_attempts_today": len(attempts),
        "unanswered_count": len(unanswered),
        "by_curriculum": {k: len(v) for k, v in by_prefix.items()},
        "weak_areas": prog.get("weak_areas", []),
        "due_quizzes_total": prog["summary"]["due_reviews"],
        "attempts": [dict(a) for a in attempts],
        "unanswered_topics": list({u["topic"] for u in unanswered}),
        "sample_unanswered": [
            {"id": u["id"], "topic": u["topic"], "question": u["question"][:120]}
            for u in unanswered[:8]
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
