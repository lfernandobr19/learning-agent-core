"""Boost quiz mastery finance-lead — remediação de falhas + banco financeiro."""

from __future__ import annotations

import re
from typing import Any

from learning_agent import db
from learning_agent.core import agent_collaboration, knowledge, llm as llm_core, quiz

AGENT = "finance-lead"

FINANCE_QUIZ_POOL: list[dict[str, str]] = [
    {
        "topic": "finance-lead — FIIs",
        "question": "Como a vacância afeta o dividend yield de um FII?",
        "answer": "Maior vacância reduz receita de aluguéis e pressiona distribuições; yield pode cair ou ficar insustentável.",
    },
    {
        "topic": "finance-lead — FIIs",
        "question": "O que indica P/VP abaixo de 1,0 em um FII?",
        "answer": "Mercado precifica patrimônio abaixo do valor contábil; pode ser oportunidade ou risco de ativos deteriorados.",
    },
    {
        "topic": "finance-lead — renda fixa",
        "question": "Qual a diferença prática entre prefixado e IPCA+?",
        "answer": "Prefixado trava taxa nominal; IPCA+ protege purchasing power somando inflação a um spread real.",
    },
    {
        "topic": "finance-lead — macro",
        "question": "Como alta da Selic tende a afetar FIIs de papel?",
        "answer": "Taxa de desconto sobe, preço do FII cai; crédito mais caro pode aumentar inadimplência nos ativos.",
    },
    {
        "topic": "finance-lead — risco",
        "question": "O que é drawdown em paper trading?",
        "answer": "Queda percentual do pico ao vale da curva de capital; mede stress da estratégia.",
    },
    {
        "topic": "finance-lead — tributação",
        "question": "Como PF tributa ganho de capital em ações na B3?",
        "answer": "15% sobre lucro na venda; isento até R$ 20 mil de vendas no mês para ações comuns.",
    },
    {
        "topic": "finance-lead — ETFs",
        "question": "Para que serve BOVA11 na carteira de um PF?",
        "answer": "Exposição diversificada ao Ibovespa com liquidez e custódia simples via ETF.",
    },
    {
        "topic": "finance-lead — valuation",
        "question": "Quando P/L alto pode ser justificável?",
        "answer": "Empresas com alto crescimento de lucro, margens expandindo ou vantagem competitiva durável.",
    },
]


def _finance_tags() -> list[str]:
    tags = [t.lower() for t in agent_collaboration._learning_tags(AGENT)]
    tags.extend(["finance-lead", "peer-finance-lead", "finance", "investimento", "fii", "fiis"])
    return tags


def _topic_matches(topic: str, tags: list[str]) -> bool:
    low = topic.lower()
    return any(tag in low for tag in tags if len(tag) >= 3)


def get_remediation_queue(*, limit: int = 12) -> list[dict[str, Any]]:
    """Itens finance cujo último attempt foi incorreto ou ainda sem resposta."""
    tags = _finance_tags()
    db.init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT qi.id, qi.topic, qi.question, qi.answer,
                   qa.correct AS last_correct,
                   qa.id AS last_attempt_id
            FROM quiz_items qi
            LEFT JOIN quiz_attempts qa ON qa.id = (
                SELECT id FROM quiz_attempts
                WHERE quiz_item_id = qi.id
                ORDER BY id DESC LIMIT 1
            )
            WHERE qa.correct = 0 OR qa.id IS NULL
            ORDER BY qa.id IS NULL DESC, qi.id ASC
            """
        ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        if _topic_matches(str(row["topic"]), tags):
            out.append(dict(row))
        if len(out) >= limit:
            break
    return out


def seed_finance_quizzes(*, count: int = 3) -> dict[str, Any]:
    """Insere perguntas financeiras se o banco estiver fino."""
    import random

    selected = random.sample(
        FINANCE_QUIZ_POOL, k=min(count, len(FINANCE_QUIZ_POOL))
    )
    return quiz.insert_curriculum_questions(selected, skip_existing=True)


def _answer_with_context(question: str, expected: str, topic: str) -> tuple[str, bool]:
    from learning_agent.core.agent_learning_loop import _evaluate_quiz_answer

    hits = knowledge.search(f"{topic} {question}"[:120], limit=3)
    ctx = "\n".join(
        f"- {(h.get('content') or h.get('title') or '')[:300]}"
        for h in (hits or [])
        if h
    )
    system = (
        "Você é finance-lead, especialista em investimentos PF Brasil. "
        "Responda o quiz de forma concisa e factual (2-4 frases). "
        "Use o contexto local se relevante."
    )
    user = f"Tópico: {topic}\nPergunta: {question}\n"
    if ctx.strip():
        user += f"\nContexto:\n{ctx}\n"
    user += "\nResposta:"

    try:
        answer, _ = llm_core.chat_with_fallback(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=220,
            temperature=0.25,
        )
    except Exception as exc:
        return f"erro: {exc}", False

    correct = _evaluate_quiz_answer(expected, answer)
    return answer, correct


def run_quiz_remediation(*, max_items: int = 8) -> dict[str, Any]:
    """Re-responde falhas financeiras — acelera mastery (último attempt por item)."""
    queue = get_remediation_queue(limit=max_items)
    seeded = 0
    if len(queue) < max(3, max_items // 2):
        seed = seed_finance_quizzes(count=3)
        seeded = int(seed.get("total") or 0)
        if seeded:
            queue = get_remediation_queue(limit=max_items)

    reviewed: list[dict[str, Any]] = []
    for item in queue[:max_items]:
        qid = int(item["id"])
        question = str(item["question"])
        expected = str(item.get("answer") or "")
        topic = str(item.get("topic") or AGENT)

        if not expected:
            db.init_db()
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT answer FROM quiz_items WHERE id = ?", (qid,)
                ).fetchone()
                if row:
                    expected = str(row["answer"])

        answer, correct = _answer_with_context(question, expected, topic)
        quiz.record_answer(qid, correct=correct, response=answer[:400])
        reviewed.append(
            {
                "quiz_id": qid,
                "topic": topic,
                "question": question[:80],
                "correct": correct,
            }
        )

    correct_n = sum(1 for r in reviewed if r["correct"])
    if reviewed:
        knowledge.add_note(
            f"[Quiz boost] finance-lead",
            "\n".join(
                f"{'OK' if r['correct'] else 'FAIL'} — {r['topic']}: {r['question']}"
                for r in reviewed
            ),
            tags=["quiz", "finance-lead", "remediation", "agent:finance-lead"],
            sync_cloud=False,
        )

    return {
        "success": True,
        "action": "finance_quiz_remediation",
        "agent": AGENT,
        "seeded": seeded,
        "reviewed": reviewed,
        "correct": correct_n,
        "total": len(reviewed),
    }
