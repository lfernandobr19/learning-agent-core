from pathlib import Path

from learning_agent import db
from learning_agent import rag
from learning_agent.config import DOCS_PATH

INDEXABLE_SUFFIXES = {".md", ".txt", ".py", ".js", ".ts", ".json", ".html", ".css"}


def infer_tags(path: Path) -> list[str]:
    tags: list[str] = []
    try:
        parts = path.relative_to(DOCS_PATH).parts
    except ValueError:
        parts = path.parts
    for part in parts[:-1]:
        if part not in {"docs", "."}:
            tags.append(part.lower())
    if path.stem == "curriculo":
        tags.append("curriculo")
    return tags


def index_file(path: Path, tags: list[str] | None = None) -> str | None:
    if not path.is_file():
        return None
    if path.suffix.lower() not in INDEXABLE_SUFFIXES:
        return None
    if path.name.startswith("."):
        return None

    db.init_db()
    tag_list = tags if tags is not None else infer_tags(path)
    return rag.index_file(path, tag_list)


def index_docs_dir(docs_dir: Path | None = None, extra_tags: list[str] | None = None) -> list[str]:
    target = docs_dir or DOCS_PATH
    if not target.exists():
        return []

    indexed: list[str] = []
    for path in sorted(target.glob("**/*")):
        if not path.is_file():
            continue
        tags = infer_tags(path)
        if extra_tags:
            tags = list(dict.fromkeys(tags + extra_tags))
        doc_id = index_file(path, tags)
        if doc_id:
            indexed.append(doc_id)
    return indexed
