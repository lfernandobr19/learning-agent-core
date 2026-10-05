"""Testes — filtros de conversa por projeto, grep, plugins, debug."""

from __future__ import annotations

from pathlib import Path

import pytest

from learning_agent import db
from learning_agent.core import chat
from learning_agent.core.ravenna_plugins import list_plugins, set_plugin_enabled
from learning_agent.core.workspace_grep import grep_workspace


@pytest.fixture()
def isolated_chat_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sqlite_path = tmp_path / "learning.db"
    monkeypatch.setattr(db, "SQLITE_PATH", sqlite_path)
    db.init_db()
    return sqlite_path


def test_list_conversations_filters_by_workspace_root_id(isolated_chat_db: Path) -> None:
    a = chat.create_conversation("ide", "RemoteApp", workspace_root_ids=["remote_app"])
    b = chat.create_conversation("ide", "Finance", workspace_root_ids=["finance"])
    chat.on_user_message(a["id"], "msg remote_app")
    chat.on_user_message(b["id"], "msg finance")
    with db.get_connection() as conn:
        for conv_id, content in ((a["id"], "msg remote_app"), (b["id"], "msg finance")):
            conn.execute(
                """
                INSERT INTO chat_messages (channel, user_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ide", conv_id, "user", content, db._utcnow()),
            )

    remote_app_removed = chat.list_conversations("ide", workspace_root_id="remote_app")
    assert len(remote_app_removed) == 1
    assert remote_app_removed[0]["id"] == a["id"]

    finance_only = chat.list_conversations("ide", workspace_root_id="finance")
    assert len(finance_only) == 1
    assert finance_only[0]["id"] == b["id"]


def test_workspace_grep_python_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "main.py").write_text("def hello():\n    return 'grep_me'\n", encoding="utf-8")

    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(root))
    from learning_agent.core import workspace_roots

    registry = tmp_path / "roots.json"
    monkeypatch.setattr(workspace_roots, "REGISTRY_PATH", registry)
    roots = workspace_roots.list_roots()
    root_id = roots[0]["id"]
    result = grep_workspace(root_id, "grep_me")
    assert result["count"] >= 1
    assert any("grep_me" in hit["text"] for hit in result["results"])


def test_plugins_catalog_and_toggle() -> None:
    plugins = list_plugins()
    assert any(p["id"] == "ravenna.ravenna-ai" for p in plugins)
    toggled = set_plugin_enabled("ravenna.sample-tools", False)
    assert toggled["enabled"] is False


def test_api_workspace_grep_and_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("print('marker_xyz')\n", encoding="utf-8")
    monkeypatch.setenv("RAVENNA_WORKSPACE_ROOT", str(root))
    from learning_agent.core import workspace_roots
    from learning_agent.core.debug_session import create_session

    registry = tmp_path / "roots.json"
    monkeypatch.setattr(workspace_roots, "REGISTRY_PATH", registry)
    root_id = workspace_roots.list_roots()[0]["id"]

    grep = grep_workspace(root_id, "marker_xyz")
    assert grep["count"] >= 1

    plugins = list_plugins()
    assert len(plugins) >= 2

    session = create_session(root_id, "app.py")
    assert session.id
