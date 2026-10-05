from __future__ import annotations

from pathlib import Path

import pytest

from learning_agent import db
from learning_agent.core import chat


@pytest.fixture()
def isolated_chat_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sqlite_path = tmp_path / "learning.db"
    monkeypatch.setattr(db, "SQLITE_PATH", sqlite_path)
    db.init_db()
    return sqlite_path


def test_conversation_project_metadata_is_persisted(isolated_chat_db: Path) -> None:
    created = chat.create_conversation(
        "ide",
        "Sessao RemoteApp",
        project_name="RemoteApp",
        project_root="C:/work/RemoteApp",
        workspace_root_ids=["remote_app"],
    )
    chat.on_user_message(created["id"], "Primeira mensagem da sessão")
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (channel, user_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("ide", created["id"], "user", "Primeira mensagem da sessão", db._utcnow()),
        )

    listed = chat.list_conversations("ide")

    assert listed[0]["id"] == created["id"]
    assert listed[0]["project_name"] == "RemoteApp"
    assert listed[0]["project_root"] == "C:/work/RemoteApp"
    assert listed[0]["workspace_root_ids"] == ["remote_app"]


def test_empty_conversations_are_hidden_from_history(isolated_chat_db: Path) -> None:
    chat.create_conversation("ide", "Rascunho vazio")
    assert chat.list_conversations("ide") == []

