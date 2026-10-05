import random
from datetime import datetime, timedelta, timezone
from typing import Any

from learning_agent import db
from learning_agent import sync
from learning_agent.core import proofs

SAMPLE_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "python": [
        {
            "question": "O que faz o decorator @property em Python?",
            "answer": "Transforma um método em um atributo somente leitura acessível sem parênteses.",
        },
        {
            "question": "Qual a diferença entre list e tuple?",
            "answer": "List é mutável; tuple é imutável.",
        },
    ],
    "javascript": [
        {
            "question": "O que é closure em JavaScript?",
            "answer": "Função que mantém acesso ao escopo léxico onde foi criada.",
        },
        {
            "question": "Diferença entre == e ===?",
            "answer": "== faz coerção de tipo; === compara valor e tipo.",
        },
    ],
    "general": [
        {
            "question": "O que é complexidade O(n)?",
            "answer": "Tempo de execução cresce linearmente com o tamanho da entrada.",
        },
        {
            "question": "O que é uma API REST?",
            "answer": "Interface HTTP que usa verbos padrão para manipular recursos.",
        },
    ],
}


def _next_review_date(interval_days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=interval_days)).isoformat()


def _update_sm2(item_id: int, correct: bool) -> None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT ease_factor, interval_days, repetitions FROM quiz_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return

        ease = row["ease_factor"]
        interval = row["interval_days"]
        reps = row["repetitions"]

        if correct:
            reps += 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 3
            else:
                interval = max(1, int(interval * ease))
            ease = min(3.0, ease + 0.1)
        else:
            reps = 0
            interval = 1
            ease = max(1.3, ease - 0.2)

        conn.execute(
            """
            UPDATE quiz_items
            SET ease_factor = ?, interval_days = ?, repetitions = ?, next_review = ?
            WHERE id = ?
            """,
            (ease, interval, reps, _next_review_date(interval), item_id),
        )


def insert_curriculum_questions(
    questions: list[dict[str, str]],
    *,
    skip_existing: bool = True,
) -> dict[str, Any]:
    """Insere perguntas de currículo; evita duplicar topic+question idênticos."""
    db.init_db()
    now = db._utcnow()
    created: list[dict[str, Any]] = []
    skipped = 0

    with db.get_connection() as conn:
        for item in questions:
            topic = item["topic"]
            question = item["question"]
            answer = item["answer"]
            if skip_existing:
                exists = conn.execute(
                    "SELECT id FROM quiz_items WHERE topic = ? AND question = ? LIMIT 1",
                    (topic, question),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
            cursor = conn.execute(
                """
                INSERT INTO quiz_items (topic, question, answer, next_review, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic, question, answer, now, now),
            )
            created.append(
                {"id": cursor.lastrowid, "topic": topic, "question": question}
            )

    return {
        "total": len(created),
        "skipped": skipped,
        "questions": created,
    }


def create_quiz(topic: str = "general", count: int = 3) -> dict[str, Any]:
    db.init_db()
    topic_key = topic.lower()
    if topic_key in {"peer-finance-lead", "finance-lead"}:
        from learning_agent.core.finance_quiz_boost import FINANCE_QUIZ_POOL

        pool = [
            {"question": x["question"], "answer": x["answer"]} for x in FINANCE_QUIZ_POOL
        ]
    else:
        pool = SAMPLE_QUESTIONS.get(topic_key, SAMPLE_QUESTIONS["general"])
    selected = random.sample(pool, k=min(count, len(pool)))
    now = db._utcnow()
    created: list[dict[str, Any]] = []

    with db.get_connection() as conn:
        for item in selected:
            cursor = conn.execute(
                """
                INSERT INTO quiz_items (topic, question, answer, next_review, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic, item["question"], item["answer"], now, now),
            )
            created.append(
                {
                    "id": cursor.lastrowid,
                    "topic": topic,
                    "question": item["question"],
                }
            )

    return {"topic": topic, "questions": created}


def record_answer(quiz_item_id: int, correct: bool, response: str = "") -> dict[str, Any]:
    db.init_db()
    now = db._utcnow()

    with db.get_connection() as conn:
        item = db.row_to_dict(
            conn.execute("SELECT * FROM quiz_items WHERE id = ?", (quiz_item_id,)).fetchone()
        )
        if not item:
            raise ValueError(f"Quiz item {quiz_item_id} not found")

        conn.execute(
            """
            INSERT INTO quiz_attempts (quiz_item_id, correct, response, attempted_at)
            VALUES (?, ?, ?, ?)
            """,
            (quiz_item_id, int(correct), response, now),
        )

    _update_sm2(quiz_item_id, correct)

    with db.get_connection() as conn:
        updated = db.row_to_dict(
            conn.execute("SELECT * FROM quiz_items WHERE id = ?", (quiz_item_id,)).fetchone()
        )

    result = {
        "quiz_item_id": quiz_item_id,
        "correct": correct,
        "next_review": updated["next_review"] if updated else None,
        "interval_days": updated["interval_days"] if updated else None,
    }
    result = sync.attach_cloud_sync(result)
    return proofs.attach_proofs(result)
