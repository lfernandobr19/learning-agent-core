"""Testes — metodologia de estudo estruturado por agente."""

from learning_agent.core import agent_study_methodology
from learning_agent.core.agent_capability import CORE_AGENTS


def test_practice_maps_all_core_archetypes():
    from learning_agent.core import agent_collaboration

    for slug in CORE_AGENTS:
        manifest = agent_collaboration._load_manifest(slug) or {}
        archetype = manifest.get("archetype", "custom")
        assert archetype in agent_study_methodology.PRACTICE_BY_ARCHETYPE or archetype == "custom"


def test_pick_next_agent_prioritizes_low_l6(monkeypatch, tmp_path):
    parity = tmp_path / "model_parity.json"
    parity.write_text(
        """{
          "agents": {
            "backend-lead": {"assessed": true, "composite_score": 90},
            "data-engineer": {"assessed": true, "composite_score": 72,
              "dimensions": {"decision": {"score": 60}}},
            "reliability-lead": {"assessed": true, "composite_score": 75}
          }
        }""",
        encoding="utf-8",
    )
    state = tmp_path / "agent_study_state.json"
    monkeypatch.setattr(agent_study_methodology, "MODEL_PARITY_STATE_PATH", parity)
    monkeypatch.setattr(agent_study_methodology, "STATE_PATH", state)

    picked = agent_study_methodology.pick_next_agent()
    assert picked == "data-engineer"


def test_weakest_dimension_from_parity(monkeypatch, tmp_path):
    parity = tmp_path / "model_parity.json"
    parity.write_text(
        """{
          "agents": {
            "reliability-lead": {
              "dimensions": {
                "decision": {"score": 60},
                "architecture": {"score": 85}
              }
            }
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_study_methodology, "MODEL_PARITY_STATE_PATH", parity)
    assert agent_study_methodology._weakest_dimension("reliability-lead") == "decision"


def test_needs_strict_parity_when_composite_ok_but_dimension_weak(monkeypatch, tmp_path):
    parity = tmp_path / "model_parity.json"
    parity.write_text(
        """{
          "agents": {
            "finance-lead": {
              "assessed": true,
              "composite_score": 83.6,
              "dimensions": {
                "knowledge": {"score": 90},
                "reasoning": {"score": 70},
                "decision": {"score": 92}
              }
            }
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_study_methodology, "MODEL_PARITY_STATE_PATH", parity)

    assert agent_study_methodology._needs_strict_parity("finance-lead") is True
    assert agent_study_methodology._weak_dimensions("finance-lead") == ["reasoning"]
    diag = agent_study_methodology._phase_diagnose("finance-lead")
    assert diag["needs_l6"] is True
    assert diag["weak_dimensions"] == ["reasoning"]


def test_needs_strict_parity_false_when_all_dimensions_met(monkeypatch, tmp_path):
    parity = tmp_path / "model_parity.json"
    parity.write_text(
        """{
          "agents": {
            "finance-lead": {
              "assessed": true,
              "composite_score": 86,
              "dimensions": {
                "knowledge": {"score": 85},
                "reasoning": {"score": 82},
                "decision": {"score": 90}
              }
            }
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_study_methodology, "MODEL_PARITY_STATE_PATH", parity)

    assert agent_study_methodology._needs_strict_parity("finance-lead") is False
    assert agent_study_methodology._phase_diagnose("finance-lead")["needs_l6"] is False
