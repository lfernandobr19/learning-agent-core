"""Indexação semântica do código-fonte com chunking inteligente."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from learning_agent import rag
from learning_agent.config import PROJECT_ROOT

CODE_SUFFIXES = {".py", ".ts", ".js", ".tsx", ".jsx"}
SKIP_DIRS = {".venv", "data", "__pycache__", ".git", "node_modules", ".cursor", "dist", "build"}
DEFAULT_DIRS = ("learning_agent",)
MAX_CHUNK_CHARS = 2400


def _should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def _chunk_python(source: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    lines = source.splitlines()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _chunk_by_size(source, "block")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = node.end_lineno or node.lineno
            text = "\n".join(lines[node.lineno - 1 : end])
            if text.strip():
                chunks.append(
                    {
                        "name": node.name,
                        "kind": type(node).__name__,
                        "content": text[:MAX_CHUNK_CHARS],
                        "line_start": node.lineno,
                        "line_end": end,
                    }
                )
    if not chunks:
        return _chunk_by_size(source, "file")
    return chunks


def _chunk_by_size(text: str, kind: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    start = 0
    idx = 0
    while start < len(text):
        piece = text[start : start + MAX_CHUNK_CHARS]
        if piece.strip():
            chunks.append({"name": f"chunk_{idx}", "kind": kind, "content": piece, "line_start": 0, "line_end": 0})
        start += MAX_CHUNK_CHARS
        idx += 1
    return chunks or [{"name": "empty", "kind": kind, "content": text, "line_start": 0, "line_end": 0}]


def _chunk_markdown(source: str) -> list[dict[str, Any]]:
    parts = re.split(r"(?=^#{1,3} )", source, flags=re.MULTILINE)
    chunks: list[dict[str, Any]] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        title = part.splitlines()[0].lstrip("# ").strip() if part.startswith("#") else f"section_{i}"
        chunks.append(
            {
                "name": title[:80],
                "kind": "markdown_section",
                "content": part[:MAX_CHUNK_CHARS],
                "line_start": 0,
                "line_end": 0,
            }
        )
    return chunks or _chunk_by_size(source, "markdown")


def chunk_file(path: Path) -> list[dict[str, Any]]:
    source = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".py":
        return _chunk_python(source)
    if path.suffix == ".md":
        return _chunk_markdown(source)
    return _chunk_by_size(source, path.suffix.lstrip(".") or "text")


def index_file(path: Path, extra_tags: list[str] | None = None) -> list[str]:
    if not path.is_file() or _should_skip(path):
        return []
    if path.suffix.lower() not in CODE_SUFFIXES and path.suffix != ".md":
        return []

    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = str(path)

    tags = list(extra_tags or []) + ["codebase", path.suffix.lstrip(".")]
    indexed: list[str] = []

    for i, chunk in enumerate(chunk_file(path)):
        doc_id = f"code:{rel}:{chunk['name']}:{i}"
        header = f"File: {rel}\n{chunk['kind']}: {chunk['name']}\nLines: {chunk['line_start']}-{chunk['line_end']}\n\n"
        rag.index_document(
            doc_id,
            header + chunk["content"],
            {
                "type": "code_chunk",
                "source": rel,
                "symbol": chunk["name"],
                "kind": chunk["kind"],
                "tags": ",".join(tags),
            },
        )
        indexed.append(doc_id)
    return indexed


def index_codebase(
    dirs: list[str] | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any]:
    targets = dirs or list(DEFAULT_DIRS)
    indexed_files = 0
    indexed_chunks = 0
    files: list[str] = []

    for dir_name in targets:
        root = PROJECT_ROOT / dir_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or _should_skip(path):
                continue
            if path.suffix.lower() not in CODE_SUFFIXES and path.suffix != ".md":
                continue
            chunks = index_file(path, extra_tags)
            if chunks:
                indexed_files += 1
                indexed_chunks += len(chunks)
                files.append(path.relative_to(PROJECT_ROOT).as_posix())

    return {
        "success": True,
        "indexed_files": indexed_files,
        "indexed_chunks": indexed_chunks,
        "files": files[:30],
    }


def search_code(query: str, limit: int = 5) -> list[dict[str, Any]]:
    results = rag.search_knowledge(query, limit=limit * 3)
    code_hits = [r for r in results if r.get("metadata", {}).get("type") == "code_chunk"]
    return code_hits[:limit]
