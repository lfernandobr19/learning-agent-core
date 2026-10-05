from learning_agent.core import agent_project_profiles, agent_spec_builder
from scripts.cursor_supervise_ravenna_home import EPICS, TRAINING_PREFIX


def test_training_prefix_does_not_trigger_fulfillment_semantic_rule():
    rules = agent_spec_builder._semantic_rules(TRAINING_PREFIX)
    assert "event-sourcing" not in rules


def test_mesma_pagina_does_not_trigger_esm_rule():
    text = "Não empilhar tudo na mesma página."
    rules = agent_spec_builder._semantic_rules(text)
    assert "esm-no-require" not in rules


def test_ravenna_home_profile_strips_benchmark_rules():
    msg = TRAINING_PREFIX + next(e["brief"] for e in EPICS if e["id"] == "rh-07-complete")
    spec = agent_spec_builder.build_spec(msg, project_root="ravenna-home/frontend")
    assert spec.get("ravennaHome") is True
    assert "event-sourcing" not in (spec.get("semanticRules") or [])
    assert "ravenna-home-web" in " ".join(spec.get("validationCommands") or [])


def test_ravenna_home_final_profile_has_deploy_gate():
    msg = "rh-07-final com gates duros e abas visíveis"
    spec = agent_spec_builder.build_spec(msg, project_root="ravenna-home/frontend")
    assert spec.get("ravennaHomeDeploy") is True
    assert spec.get("ravennaHomeRemoteValidation") is True
    cmds = spec.get("validationCommands") or []
    assert cmds and "ravenna-home-web" in cmds[0]
    assert "src/App.js" in (spec.get("forbiddenPaths") or [])


def test_ravenna_home_cursor_bar_profile():
    msg = TRAINING_PREFIX + next(e["brief"] for e in EPICS if e["id"] == "rh-07-cursor-bar")
    spec = agent_spec_builder.build_spec(msg, project_root="ravenna-home/frontend")
    assert spec.get("ravennaHomeRemoteValidation") is True
    assert "npm run build" not in " ".join(spec.get("validationCommands") or [])


def test_fulfillment_benchmark_still_detected_for_real_bench_prompt():
    text = "Crie src/fulfillment.js com event-sourced order fulfillment."
    assert agent_project_profiles.mentions_fulfillment_benchmark(text) is True
