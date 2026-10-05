"""Testes — gerador de benchmark cego."""

from __future__ import annotations

from learning_agent.scripts import generate_blind_benchmark


def test_generate_blind_dry_run():
    out = generate_blind_benchmark.generate_blind("finance-lead", use_llm=False, dry_run=True)
    assert out["success"]
    assert out["blind_id"].startswith("blind_")
    assert out["dry_run"] is True
