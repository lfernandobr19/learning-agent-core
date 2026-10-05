"""Sprint real — reliability-lead: proof suite."""
from learning_agent.core import proofs


def test_sprint_reliability_lead_proof_suite_runs():
    suite = proofs.run_full_proof_suite()
    assert "checks" in suite
    assert suite.get("total", 0) >= 3
    names = {c["check"] for c in suite.get("checks", [])}
    assert "sqlite" in names
