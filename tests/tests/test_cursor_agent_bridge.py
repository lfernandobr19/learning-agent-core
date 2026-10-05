"""Testes — ponte Telegram → Cursor SDK."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from learning_agent.core import cursor_agent_bridge as cab


def test_is_consult_request():
    assert cab.is_consult_request("/cursor status do finance")
    assert cab.is_consult_request("Fala com o cursor: as sugestões foram aplicadas?")
    assert cab.is_consult_request("Ravenna, fale com o cursor: status")
    assert not cab.is_consult_request("Qual a capital da França?")


def test_strip_consult_prefix():
    assert cab._strip_consult_prefix("/cursor o que mudou?") == "o que mudou?"
    assert "aplicadas" in cab._strip_consult_prefix("fala com o cursor: foram aplicadas?")


@patch.dict("os.environ", {"CURSOR_API_KEY": "test-key", "CURSOR_BRIDGE_ENABLED": "true"})
def test_consult_not_configured_without_sdk(monkeypatch):
    monkeypatch.setattr(cab, "is_configured", lambda: False)
    monkeypatch.setattr(cab, "configuration_hint", lambda: "instale cursor-sdk")
    out = cab.consult("u1", "pergunta teste")
    assert not out["success"]
    assert "cursor-sdk" in out["error"]


@patch.dict("os.environ", {"CURSOR_API_KEY": "test-key"})
def test_consult_success(monkeypatch, tmp_path):
    monkeypatch.setattr(cab, "SESSIONS_PATH", tmp_path / "sessions.json")
    monkeypatch.setattr(cab, "CONSULT_LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(cab, "is_configured", lambda: True)
    monkeypatch.setattr(cab, "build_context_block", lambda **kw: "CTX")

    mock_block = MagicMock(type="text", text="Sim, 3 diretivas aplicadas.")
    mock_msg = MagicMock(type="assistant", message=MagicMock(content=[mock_block]))
    mock_run = MagicMock(status="completed", result=MagicMock(result="Sim, 3 diretivas aplicadas."))
    mock_run.messages.return_value = [mock_msg]

    mock_agent = MagicMock()
    mock_agent.id = "agent-abc"
    mock_agent.send.return_value = mock_run

    class FakeCtx:
        def __enter__(self):
            return mock_agent

        def __exit__(self, *a):
            return False

    fake_agent_mod = MagicMock()
    fake_agent_mod.Agent.create.return_value = FakeCtx()
    fake_agent_mod.AgentOptions = MagicMock()
    fake_agent_mod.LocalAgentOptions = MagicMock()
    fake_agent_mod.CursorAgentError = Exception
    monkeypatch.setitem(__import__("sys").modules, "cursor_sdk", fake_agent_mod)

    out = cab.consult("u1", "/cursor as sugestões foram aplicadas?")
    assert out["success"]
    assert "3 diretivas" in out["reply"]


def test_reset_session(tmp_path, monkeypatch):
    monkeypatch.setattr(cab, "SESSIONS_PATH", tmp_path / "sessions.json")
    cab._set_session("u9", "agent-x")
    cab.reset_session("u9")
    assert cab._get_session("u9") == {}
