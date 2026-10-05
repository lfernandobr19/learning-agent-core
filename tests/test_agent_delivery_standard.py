from learning_agent.core import agent_delivery_standard, agent_spec_builder


def test_agent_mode_gets_cursor_equivalent_delivery_flag():
    spec = agent_spec_builder.build_spec("Implemente feature X em src/app.ts", project_root="my-app")
    assert spec.get("cursorEquivalentDelivery") is True


def test_audit_only_skips_delivery_flag():
    spec = agent_spec_builder.build_spec(
        "Épico só diagnóstico — sem write/patch/shell",
        project_root="my-app",
    )
    assert spec.get("cursorEquivalentDelivery") is not True


def test_integration_failures_detect_orphan_app_js():
    failures = agent_delivery_standard.integration_failures(
        ["ravenna-home/frontend/src/App.js"],
        project_root="ravenna-home/frontend",
    )
    assert failures
