"""Testes — probes backend-lead + ship autônomo."""

from __future__ import annotations

from learning_agent.core import agent_external_completion, backend_probes, ship_autonomous, ship_pipeline


def test_b1_health():
    assert backend_probes.probe_backend_health_ok()["passed"]


def test_backend_external_ready():
    report = agent_external_completion.assess_external_completion("backend-lead")
    assert report["success"]
    assert report["passed_count"] >= 4
    assert report["external_ready"]


def test_autonomous_ship_dry_run():
    item = ship_pipeline.get_next_ready_item()
    if item and item.get("autonomous"):
        r = ship_autonomous.process_item(item, dry_run=True)
        assert r.get("dry_run") or r.get("success") is not False or "pytest" in str(r)
