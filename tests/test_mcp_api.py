"""Testes — painel MCP via REST (Fase 5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.core.mcp_bridge import (
    IDE_BLOCKED_TOOLS,
    McpBridgeError,
    invoke_tool,
    list_tools,
)


def test_list_tools_has_schema():
    tools = list_tools()
    assert len(tools) >= 30
    names = {t["name"] for t in tools}
    assert "search_knowledge" in names
    assert "get_progress" in names
    sample = next(t for t in tools if t["name"] == "get_progress")
    assert "input_schema" in sample
    assert sample["ide_invokable"] is True


def test_invoke_get_progress():
    result = invoke_tool("get_progress", {})
    assert result["ok"] is True
    assert result["data"] is not None
    assert "summary" in result["data"]


def test_blocked_tool_raises():
    blocked = next(iter(IDE_BLOCKED_TOOLS))
    try:
        invoke_tool(blocked, {})
        assert False, "expected McpBridgeError"
    except McpBridgeError as exc:
        assert exc.status_code == 403


def test_api_mcp_endpoints():
    with TestClient(app) as client:
        st = client.get("/api/mcp/status")
        assert st.status_code == 200
        body = st.json()
        assert body["embedded"] is True
        assert body["tool_count"] >= 30

        tools = client.get("/api/mcp/tools")
        assert tools.status_code == 200
        assert len(tools.json()["tools"]) >= 30

        inv = client.post("/api/mcp/invoke", json={"tool": "get_next_topic", "arguments": {}})
        assert inv.status_code == 200
        assert inv.json()["ok"] is True

        bad = client.post("/api/mcp/invoke", json={"tool": "start_teaching_theater"})
        assert bad.status_code == 403
