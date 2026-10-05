"""Sprint real — data-engineer: índices SQLite."""
import sqlite3

from learning_agent.config import SQLITE_PATH


def test_sprint_data_engineer_indexes():
    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    ).fetchall()
    conn.close()
    names = {r[0] for r in rows}
    assert "idx_quiz_attempts_item" in names
    assert "idx_agent_exchanges_thread" in names
