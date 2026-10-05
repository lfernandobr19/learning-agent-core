"""Ripgrep no workspace — busca textual estilo VS Code Find in Files."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from learning_agent.core.workspace_roots import WorkspaceRootsError, get_root_path

MAX_RESULTS = 200
DEFAULT_IGNORE = (
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
)


def _walk_grep(root_path, pattern: str, *, max_results: int) -> list[dict[str, Any]]:
    """Fallback Python quando rg não está disponível."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise WorkspaceRootsError(f"Padrão inválido: {exc}", status_code=400) from exc

    hits: list[dict[str, Any]] = []
    stack = [root_path]
    while stack and len(hits) < max_results:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name in DEFAULT_IGNORE or entry.name.startswith("."):
                continue
            if entry.is_dir():
                stack.append(entry)
                continue
            if not re.search(r"\.(py|ts|tsx|js|jsx|css|html|md|yaml|yml|json|toml|rs|go)$", entry.name, re.I):
                continue
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = entry.relative_to(root_path).as_posix()
                    hits.append(
                        {
                            "path": rel,
                            "line": line_no,
                            "column": max(line.lower().find(pattern.lower()), 0) + 1,
                            "text": line.strip()[:300],
                        }
                    )
                    if len(hits) >= max_results:
                        break
    return hits


def grep_workspace(
    root_id: str,
    pattern: str,
    *,
    max_results: int = MAX_RESULTS,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    if not root_id.strip():
        raise WorkspaceRootsError("root_id obrigatório", status_code=400)
    if not pattern.strip():
        raise WorkspaceRootsError("pattern obrigatório", status_code=400)

    root_path = get_root_path(root_id)
    limit = max(1, min(max_results, MAX_RESULTS))
    rg = shutil.which("rg")

    if rg:
        cmd = [
            rg,
            "--json",
            "--line-number",
            "--column",
            "--max-count",
            str(limit),
            "--glob",
            "!.git/**",
            "--glob",
            "!node_modules/**",
            "--glob",
            "!.venv/**",
            "--glob",
            "!dist/**",
            "--glob",
            "!build/**",
        ]
        if not case_sensitive:
            cmd.append("-i")
        cmd.extend([pattern, str(root_path)])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceRootsError(f"grep falhou: {exc}", status_code=500) from exc

        hits: list[dict[str, Any]] = []
        for raw in (proc.stdout or "").splitlines():
            if len(hits) >= limit:
                break
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "match":
                continue
            data = row.get("data") or {}
            path_raw = (data.get("path") or {}).get("text") or ""
            rel = path_raw
            try:
                rel = str(__import__("pathlib").Path(path_raw).relative_to(root_path))
            except ValueError:
                rel = path_raw.replace("\\", "/")
            line_no = (data.get("line_number") or 1)
            sub = (data.get("submatches") or [{}])[0]
            col = (sub.get("start") or 0) + 1
            text = ((data.get("lines") or {}).get("text") or "").strip()
            hits.append({"path": rel.replace("\\", "/"), "line": line_no, "column": col, "text": text[:300]})

        return {
            "root_id": root_id,
            "pattern": pattern,
            "engine": "ripgrep",
            "count": len(hits),
            "results": hits,
        }

    hits = _walk_grep(root_path, pattern, max_results=limit)
    return {
        "root_id": root_id,
        "pattern": pattern,
        "engine": "python",
        "count": len(hits),
        "results": hits,
    }
