"""Stream emits final before slow autonomy."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest


def _parse_ndjson(chunks: list[str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in chunks:
        for line in chunk.splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def test_chat_stream_emits_final_before_autonomy(monkeypatch: pytest.MonkeyPatch) -> None:
    from learning_agent import api as api_mod

    def fake_iter(*_a: Any, **_k: Any) -> Iterator[Any]:
        yield {"tool": {"tool": "read_file", "arguments": {"path": "a.ts"}, "result": "{}"}}
        yield {"phase": "writing"}
        yield "resposta completa"
        yield {
            "final": True,
            "reply": "resposta completa",
            "agent": "Ravenna",
            "model": "test",
            "tool_log": [{"tool": "read_file", "arguments": {"path": "a.ts"}, "result": "{}"}],
        }

    def slow_autonomy(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"enabled": True, "passed": True, "finalReply": "resposta completa", "attempts": []}

    monkeypatch.setattr(api_mod.chat, "iter_reply_deltas", fake_iter)
    monkeypatch.setattr(api_mod, "_run_agent_autonomy_cycle", slow_autonomy)
    monkeypatch.setattr(api_mod, "_build_autonomy_prompt", lambda m, p: (m, {"toolMaxTurns": 2}))
    monkeypatch.setattr(
        "learning_agent.core.ravenna_home_autonomy.tools_allowlist_for_spec",
        lambda _s: None,
    )
    monkeypatch.setattr(api_mod, "_record_autonomy_lesson", lambda *_a, **_k: None)
    monkeypatch.setattr(api_mod, "_changed_paths_from_tool_log", lambda _t: [])
    monkeypatch.setattr(api_mod, "_synthesize_tool_reply", lambda _t, m, **_k: m)
    monkeypatch.setattr(api_mod, "_synthesize_tool_write_reply", lambda _p, m: m)
    monkeypatch.setattr(api_mod, "_reply_has_chat_write", lambda _m: True)
    monkeypatch.setattr(api_mod, "_autonomy_model_size", lambda s, _sp: s or "auto")
    monkeypatch.setattr(api_mod, "_merge_tool_paths_into_autonomy", lambda a, *_x, **_y: a or {})

    req = MagicMock()
    req.message = "oi"
    req.context = ""
    req.mode = "agent"
    req.agent = ""
    req.auto_delegate = False
    req.conversation_id = "c1"
    req.persist_history = True
    req.include_context = False
    req.auto_apply = True
    req.model_size = "auto"
    req.engine = "groq"
    req.project_root = None
    req.tool_max_turns = None
    req.max_repair_attempts = 0
    req.run_checklist = False

    response = api_mod.chat_stream_endpoint(req)

    async def _collect() -> list[str]:
        out: list[str] = []
        async for chunk in response.body_iterator:
            out.append(chunk if isinstance(chunk, str) else chunk.decode())
        return out

    chunks = asyncio.run(_collect())
    events = _parse_ndjson(chunks)

    types = [e.get("type") for e in events]
    assert "final" in types
    final_idx = types.index("final")
    if "autonomy" in types:
        assert types.index("autonomy") > final_idx
    assert events[final_idx]["message"] == "resposta completa"
