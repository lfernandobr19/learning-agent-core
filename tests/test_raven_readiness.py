"""Testes — preparação total da Raven."""

from learning_agent.core import raven_readiness


def test_assess_readiness_structure():
    report = raven_readiness.assess_readiness()
    assert report["success"] is True
    assert "phases" in report
    assert len(report["phases"]) == len(raven_readiness.READINESS_PHASES)
    assert "corpus" in report
    assert "model_tiers" in report


def test_phases_have_actions():
    for phase in raven_readiness.READINESS_PHASES:
        assert phase.get("action")
        assert phase.get("phase") in {1, 2, 3, 4, 5}
