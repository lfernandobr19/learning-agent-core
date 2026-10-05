"""Testes — seleção de backend do terminal."""

from __future__ import annotations

import sys

from learning_agent.core.terminal_session import PipeBackend, create_backend


def test_create_backend_returns_pipe_or_pty():
    backend = create_backend()
    assert backend.mode in ("pipe", "pty")


def test_pipe_backend_mode():
    assert PipeBackend().mode == "pipe"
