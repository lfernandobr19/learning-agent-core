"""Testes do objetivo norte — fábrica de software."""

from learning_agent.core import software_excellence


def test_assess_excellence_structure():
    report = software_excellence.assess_excellence()
    assert report["success"] is True
    assert "factory_objectives" in report
    assert "practice_objectives" in report
    assert report["ide_is_practice_only"] is True
    assert "excelência" in software_excellence.NORTH_STAR.lower()


def test_factory_objectives_have_actions():
    for obj in software_excellence.FACTORY_OBJECTIVES:
        assert obj.get("action")
        assert obj.get("tier") == "must"


def test_practice_track_optional():
    practice = software_excellence.PRACTICE_OBJECTIVES
    assert all(o.get("tier") == "practice" for o in practice)
    assert software_excellence.COMPLETION_RULES["ide_practice_optional"] is True


def test_get_next_objective():
    nxt = software_excellence.get_next_objective()
    assert nxt["success"] is True
    if not nxt.get("complete"):
        assert "objective" in nxt or "action" in nxt.get("objective", {})


def test_brain_pipeline_dry_run():
    result = software_excellence.run_brain_pipeline(dry_run=True, broadcast_observer=False)
    assert result["success"] is True
    assert result["action"] == "brain_pipeline"
    assert "export" in result
    assert "model" in result
