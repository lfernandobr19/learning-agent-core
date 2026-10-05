"""Testes — benchmark L6 strict e mentor Cursor."""

from learning_agent.core import agent_model_parity, cursor_mentor


def test_debug_optimizer_prompts_exist():
    prompts = agent_model_parity.DOMAIN_PROMPTS["debug-optimizer"]
    assert "decision" in prompts
    assert "rollback" in prompts["decision"].lower() or "hotfix" in prompts["decision"].lower()


def test_cursor_mentor_lessons_cover_core_agents():
    from learning_agent.core.agent_capability import CORE_AGENTS

    for slug in CORE_AGENTS:
        lessons = cursor_mentor.CURSOR_MENTOR_LESSONS[slug]
        assert slug in cursor_mentor.CURSOR_MENTOR_LESSONS
        for dim in ("decision", "reasoning", "knowledge"):
            assert dim in lessons, f"{slug} sem lição {dim}"


def test_fast_capability_probe():
    probe = agent_model_parity._run_real_capability_probe("data-engineer")
    assert probe["ran"] is True
    assert probe.get("passed") is True or probe.get("infra_failure")
