import re
from pathlib import Path
from typing import Any

from learning_agent.config import DOCS_PATH, PROJECT_ROOT
from learning_agent import db

CURRICULUM_PATH = DOCS_PATH / "curriculo.md"
TOPIC_PATTERN = re.compile(r"^-\s+(.+?)\s*\|\s*(.+)$")


def _parse_curriculum(path: Path | None = None) -> list[dict[str, Any]]:
    curriculum_file = path or CURRICULUM_PATH
    if not curriculum_file.exists():
        return []

    topics: list[dict[str, Any]] = []
    current_level = "Geral"

    for line in curriculum_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current_level = line.removeprefix("## ").strip()
            continue

        match = TOPIC_PATTERN.match(line.strip())
        if not match:
            continue

        title = match.group(1).strip()
        tags = [t.strip() for t in match.group(2).split(",") if t.strip()]
        topics.append(
            {
                "title": title,
                "tags": tags,
                "level": current_level,
                "index": len(topics) + 1,
            }
        )

    return topics


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _is_topic_studied(title: str, studied_titles: set[str], studied_tags: set[str]) -> bool:
    norm_title = _normalize(title)
    if norm_title in studied_titles:
        return True

    # Match estrito: só conta se títulos são quase idênticos (evita falsos positivos)
    for studied in studied_titles:
        if norm_title == studied:
            return True
        shorter, longer = (
            (norm_title, studied) if len(norm_title) < len(studied) else (studied, norm_title)
        )
        if shorter in longer and len(shorter) / max(len(longer), 1) >= 0.9:
            return True

    return False


def get_studied_data() -> tuple[set[str], set[str]]:
    db.init_db()
    studied_titles: set[str] = set()
    studied_tags: set[str] = set()

    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT title, tags
            FROM learning_notes
            WHERE COALESCE(memory_status, 'active') != 'superseded'
            """
        ).fetchall()
        for row in rows:
            studied_titles.add(_normalize(row["title"]))
            studied_tags.update(db.parse_tags(row["tags"]))

    return studied_titles, studied_tags


def get_next_topic(curriculum_path: Path | None = None) -> dict[str, Any]:
    topics = _parse_curriculum(curriculum_path)
    if not topics:
        return {
            "found": False,
            "message": "Currículo não encontrado. Crie docs/curriculo.md",
        }

    studied_titles, studied_tags = get_studied_data()
    completed: list[str] = []
    pending: list[dict[str, Any]] = []

    for topic in topics:
        if _is_topic_studied(topic["title"], studied_titles, studied_tags):
            completed.append(topic["title"])
        else:
            pending.append(topic)

    if not pending:
        return {
            "found": True,
            "status": "completed",
            "message": "Parabéns! Você completou todo o currículo.",
            "total_topics": len(topics),
            "completed_count": len(completed),
            "completed_topics": completed,
        }

    next_topic = pending[0]
    return {
        "found": True,
        "status": "in_progress",
        "next_topic": next_topic,
        "completed_count": len(completed),
        "total_topics": len(topics),
        "progress_percent": round(len(completed) / len(topics) * 100, 1),
        "pending_count": len(pending),
        "completed_topics": completed[-5:],
    }


def get_curriculum_overview() -> dict[str, Any]:
    topics = _parse_curriculum()
    studied_titles, _ = get_studied_data()
    levels: dict[str, dict[str, int]] = {}

    for topic in topics:
        level = topic["level"]
        if level not in levels:
            levels[level] = {"total": 0, "completed": 0}
        levels[level]["total"] += 1
        if _is_topic_studied(topic["title"], studied_titles, set()):
            levels[level]["completed"] += 1

    return {
        "total_topics": len(topics),
        "levels": levels,
        "curriculum_path": str(CURRICULUM_PATH.relative_to(PROJECT_ROOT)),
    }
