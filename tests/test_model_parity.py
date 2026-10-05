"""Testes — paridade cognitiva (estrutura, sem LLM obrigatório)."""

from learning_agent.core import agent_curriculum, agent_model_parity


def test_model_parity_ecosystem_structure():
    report = agent_model_parity.assess_ecosystem_parity()
    assert report["success"] is True
    assert "north_star" in report
    assert report["cursor_integration"]["direct_cursor_models"] is False
    assert len(report["agents"]) >= 5


def test_model_parity_curriculum():
    cur = agent_curriculum.load_agent_curriculum("model-parity")
    assert cur["success"] is True
    assert cur.get("dimensions")
    assert cur.get("reference_tiers")


def test_tiers_have_reference_models():
    for tier in agent_model_parity.TIERS.values():
        assert tier.get("reference_model")
        assert tier.get("min_score") >= 60
