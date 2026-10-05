"""Unit tests for tool_log → changedPaths helpers used by chat stream."""

from __future__ import annotations

import json

from learning_agent.api import (
    _changed_paths_from_tool_log,
    _exploration_summary_from_tool_log,
    _merge_tool_paths_into_autonomy,
    _synthesize_tool_reply,
    _synthesize_tool_write_reply,
)


def test_changed_paths_from_write_file_result():
    tool_log = [
        {
            "tool": "read_file",
            "arguments": {"path": "a.py"},
            "result": '{"content":"x"}',
        },
        {
            "tool": "write_file",
            "arguments": {"path": "ravenna-ide/frontend/src/a.ts", "content": "x"},
            "result": json.dumps(
                {"changedPaths": ["ravenna-ide/frontend/src/a.ts"], "blockCount": 1}
            ),
        },
    ]
    assert _changed_paths_from_tool_log(tool_log) == ["ravenna-ide/frontend/src/a.ts"]


def test_changed_paths_skips_failed_write():
    tool_log = [
        {
            "tool": "write_file",
            "arguments": {"path": "x.ts", "content": "x"},
            "result": json.dumps({"error": "permission denied"}),
        }
    ]
    assert _changed_paths_from_tool_log(tool_log) == []


def test_synthesize_reply_when_empty():
    reply = _synthesize_tool_write_reply(["a.py", "b.ts"], "")
    assert "2 arquivo" in reply
    assert "`a.py`" in reply


def test_synthesize_keeps_existing_reply():
    assert _synthesize_tool_write_reply(["a.py"], "Feito.") == "Feito."


def test_exploration_summary_counts_reads_and_searches():
    tool_log = [
        {"tool": "read_file", "arguments": {"path": "src/a.ts"}},
        {"tool": "read_file", "arguments": {"path": "src/b.ts"}},
        {"tool": "grep_workspace", "arguments": {"query": "composer"}},
    ]
    files, searches, labels = _exploration_summary_from_tool_log(tool_log)
    assert files == 2
    assert searches == 1
    assert "a.ts" in labels
    assert "composer" in labels


def test_synthesize_tool_reply_explore_only():
    tool_log = [
        {"tool": "read_file", "arguments": {"path": "App.tsx"}},
        {"tool": "grep_workspace", "arguments": {"pattern": "vazio"}},
    ]
    reply = _synthesize_tool_reply(tool_log, "")
    assert "Explorei" in reply
    assert "arquivo" in reply
    assert "busca" in reply
    assert "`App.tsx`" in reply


def test_synthesize_tool_reply_prefers_existing():
    tool_log = [{"tool": "read_file", "arguments": {"path": "a.ts"}}]
    assert _synthesize_tool_reply(tool_log, "Já respondi.") == "Já respondi."


def test_synthesize_tool_reply_writes_over_explore():
    tool_log = [
        {"tool": "read_file", "arguments": {"path": "a.ts"}},
        {
            "tool": "write_file",
            "arguments": {"path": "b.ts", "content": "x"},
            "result": json.dumps({"changedPaths": ["b.ts"]}),
        },
    ]
    reply = _synthesize_tool_reply(tool_log, "")
    assert "Alterei" in reply
    assert "`b.ts`" in reply


def test_merge_tool_paths_into_empty_autonomy():
    autonomy = _merge_tool_paths_into_autonomy(None, ["a.py"], final_reply="ok")
    assert autonomy is not None
    assert autonomy["enabled"] is True
    assert autonomy["mergedChangedPaths"] == ["a.py"] or autonomy["attempts"][0]["applied"][
        "changedPaths"
    ] == ["a.py"]


def test_merge_tool_paths_into_existing_autonomy():
    base = {
        "enabled": True,
        "passed": False,
        "attempts": [
            {
                "attempt": 0,
                "passed": False,
                "applied": {"changedPaths": [], "blockCount": 0},
            }
        ],
        "finalReply": "",
    }
    merged = _merge_tool_paths_into_autonomy(base, ["x.ts"], final_reply="done")
    assert "x.ts" in (merged.get("mergedChangedPaths") or [])
    assert "x.ts" in merged["attempts"][-1]["applied"]["changedPaths"]
