"""Testes — mcp_external."""

from learning_agent.core import mcp_external


def test_load_external_mcp():
    r = mcp_external.load_external_mcp()
    assert r.get("success")
    assert "servers" in r


def test_spawn_dry_run_missing():
    r = mcp_external.spawn_server("nonexistent-server-xyz")
    assert r.get("success") is False
