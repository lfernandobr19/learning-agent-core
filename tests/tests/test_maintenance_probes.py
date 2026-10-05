"""Testes — probes maintenance agents (frontend, qa, data, reliability)."""

from __future__ import annotations

from learning_agent.core import agent_external_completion, maintenance_probes


def test_frontend_external_ready():
    report = agent_external_completion.assess_external_completion("frontend-lead")
    assert report["success"]
    assert report["passed_count"] >= 4
    assert report["external_ready"]


def test_qa_external_ready():
    report = agent_external_completion.assess_external_completion("qa-guardian")
    assert report["success"]
    assert report["passed_count"] >= 4
    assert report["external_ready"]


def test_data_external_ready():
    report = agent_external_completion.assess_external_completion("data-engineer")
    assert report["success"]
    assert report["passed_count"] >= 4
    assert report["external_ready"]


def test_reliability_external_ready():
    report = agent_external_completion.assess_external_completion("reliability-lead")
    assert report["success"]
    assert report["passed_count"] >= 4
    assert report["external_ready"]


def test_all_external_agents_assessed():
    report = agent_external_completion.assess_all_with_external_criteria()
    assert report["success"]
    assert report["summary"]["assessed"] == 6


def test_frontend_progress_probe():
    assert maintenance_probes.probe_frontend_progress_dashboard()["passed"]
