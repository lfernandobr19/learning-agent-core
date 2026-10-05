"""Testes — boost quiz finance-lead."""

from __future__ import annotations

from learning_agent.core import finance_quiz_boost as fqb


def test_finance_quiz_pool():
    assert len(fqb.FINANCE_QUIZ_POOL) >= 6
    assert all("question" in q and "answer" in q for q in fqb.FINANCE_QUIZ_POOL)


def test_topic_matches():
    tags = fqb._finance_tags()
    assert fqb._topic_matches("finance-lead — FIIs", tags)
    assert fqb._topic_matches("peer-finance-lead", tags)
    assert not fqb._topic_matches("Backend — HTTP", tags)


def test_remediation_queue_shape():
    queue = fqb.get_remediation_queue(limit=5)
    assert isinstance(queue, list)
    for item in queue:
        assert "id" in item
        assert "question" in item
