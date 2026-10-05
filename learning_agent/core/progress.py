from typing import Any

from learning_agent import db


def get_progress() -> dict[str, Any]:
    db.init_db()
    with db.get_connection() as conn:
        notes = db.rows_to_list(
            conn.execute(
                """
                SELECT id, title, tags, created_at
                FROM learning_notes
                WHERE COALESCE(memory_status, 'active') != 'superseded'
                ORDER BY created_at DESC
                LIMIT 20
                """
            ).fetchall()
        )
        weak_topics = db.rows_to_list(
            conn.execute(
                """
                SELECT topic, COUNT(*) as attempts,
                       SUM(CASE WHEN correct = 0 THEN 1 ELSE 0 END) as wrong_count
                FROM quiz_attempts qa
                JOIN quiz_items qi ON qi.id = qa.quiz_item_id
                GROUP BY topic
                HAVING wrong_count > 0
                ORDER BY wrong_count DESC
                LIMIT 10
                """
            ).fetchall()
        )
        due_quizzes = db.rows_to_list(
            conn.execute(
                """
                SELECT id, topic, question, next_review
                FROM quiz_items
                WHERE next_review IS NULL OR next_review <= ?
                ORDER BY next_review IS NULL DESC, next_review ASC
                LIMIT 10
                """,
                (db._utcnow(),),
            ).fetchall()
        )
        total_sessions = conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0]
        total_notes = conn.execute(
            "SELECT COUNT(*) FROM learning_notes WHERE COALESCE(memory_status, 'active') != 'superseded'"
        ).fetchone()[0]
        total_quizzes = conn.execute("SELECT COUNT(*) FROM quiz_items").fetchone()[0]

    for note in notes:
        note["tags"] = db.parse_tags(note.get("tags", "[]"))

    studied_topics = sorted({n["title"] for n in notes})
    weak_areas = [t["topic"] for t in weak_topics]

    return {
        "summary": {
            "total_notes": total_notes,
            "total_quizzes": total_quizzes,
            "total_sessions": total_sessions,
            "due_reviews": len(due_quizzes),
        },
        "recent_notes": notes,
        "studied_topics": studied_topics,
        "weak_areas": weak_areas,
        "due_quizzes": due_quizzes,
    }
