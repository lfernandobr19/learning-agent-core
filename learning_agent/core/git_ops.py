"""Git seguro no workspace — status, diff e commit (Fase 6)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from learning_agent.core.workspace import WorkspaceError, resolve_path

MAX_DIFF_BYTES = 256_000
MAX_COMMIT_MESSAGE = 500
MAX_COMMIT_PATHS = 40


class GitError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _git_binary() -> str:
    path = shutil.which("git")
    if not path:
        raise GitError("Git não encontrado no PATH", status_code=503)
    return path


def _workspace_root(root_id: str | None = None) -> Path:
    from learning_agent.core.workspace_roots import get_root_path

    return get_root_path(root_id)


def _run_git(root_id: str | None, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    git = _git_binary()
    root = _workspace_root(root_id)
    cmd = [git, "-C", str(root), *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=check,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError("Comando git excedeu o tempo limite", status_code=504) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise GitError(detail, status_code=500) from exc
    except OSError as exc:
        raise GitError(f"Falha ao executar git: {exc}", status_code=500) from exc


def _ensure_repo(root_id: str | None = None) -> Path:
    root = _workspace_root(root_id)
    if not (root / ".git").exists():
        raise GitError("Workspace não é um repositório git", status_code=404)
    return root


def init_repo(root_id: str | None = None) -> dict[str, Any]:
    root = _workspace_root(root_id)
    if (root / ".git").exists():
        raise GitError("Workspace já é um repositório git", status_code=409)
    _run_git(root_id, "init", check=True)
    return {"initialized": True, "root_id": root_id, "path": str(root)}


def _parse_porcelain(output: str) -> dict[str, list[dict[str, str]]]:
    staged: list[dict[str, str]] = []
    unstaged: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []

    for line in output.splitlines():
        if not line.strip():
            continue
        if line.startswith("?? "):
            path = line[3:].strip()
            untracked.append({"path": path, "status": "?"})
            continue
        if len(line) < 4:
            continue
        x, y = line[0], line[1]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entry = {"path": path, "status": f"{x}{y}".strip()}
        if x != " ":
            staged.append(entry)
        if y != " ":
            unstaged.append(entry)

    return {"staged": staged, "unstaged": unstaged, "untracked": untracked}


def get_status(root_id: str | None = None) -> dict[str, Any]:
    _ensure_repo(root_id)
    branch = _run_git(root_id, "branch", "--show-current", check=False)
    branch_name = (branch.stdout or "").strip() or "(detached)"

    porcelain = _run_git(root_id, "status", "--porcelain", check=False)
    parsed = _parse_porcelain(porcelain.stdout or "")

    counts = {k: len(v) for k, v in parsed.items()}
    clean = sum(counts.values()) == 0

    return {
        "branch": branch_name,
        "clean": clean,
        "counts": counts,
        **parsed,
    }


def get_diff_sides(path: str, *, staged: bool = False, root_id: str | None = None) -> dict[str, Any]:
    """Conteúdo original (HEAD/index) vs modificado — diff visual Monaco."""
    repo_root = _ensure_repo(root_id)
    if not path.strip():
        raise GitError("path obrigatório para diff visual", status_code=400)
    resolved = resolve_path(path)
    rel = resolved.relative_to(repo_root).as_posix()

    def _show(ref: str) -> str:
        result = _run_git(root_id, "show", f"{ref}:{rel}", check=False)
        if result.returncode != 0:
            return ""
        return result.stdout or ""

    from learning_agent.core.workspace import read_file

    if staged:
        original = _show("HEAD")
        modified = _show(f":{rel}") or original
    else:
        original = _show("HEAD")
        try:
            modified = str(read_file(path).get("content") or "")
        except WorkspaceError:
            modified = ""

    if not original and resolved.is_file():
        original = ""

    return {
        "path": rel,
        "staged": staged,
        "original": original,
        "modified": modified,
    }


def get_diff(path: str = "", staged: bool = False, root_id: str | None = None) -> dict[str, Any]:
    repo_root = _ensure_repo(root_id)
    args = ["diff"]
    if staged:
        args.append("--staged")
    if path and path.strip():
        resolved = resolve_path(path)
        rel = resolved.relative_to(repo_root).as_posix()
        args.extend(["--", rel])
    result = _run_git(root_id, *args, check=False)
    text = result.stdout or ""
    truncated = False
    if len(text.encode("utf-8")) > MAX_DIFF_BYTES:
        text = text[:MAX_DIFF_BYTES]
        truncated = True
    return {
        "path": path.strip() or None,
        "staged": staged,
        "diff": text,
        "truncated": truncated,
    }


def _validate_commit_message(message: str) -> str:
    msg = (message or "").strip()
    if not msg:
        raise GitError("Mensagem de commit obrigatória", status_code=400)
    if len(msg) > MAX_COMMIT_MESSAGE:
        raise GitError(f"Mensagem muito longa (máx {MAX_COMMIT_MESSAGE})", status_code=400)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", msg):
        raise GitError("Mensagem de commit inválida", status_code=400)
    return msg


def _validate_paths(paths: list[str], root_id: str | None = None) -> list[str]:
    if not paths:
        raise GitError("Informe ao menos um arquivo para commit", status_code=400)
    if len(paths) > MAX_COMMIT_PATHS:
        raise GitError(f"Máximo de {MAX_COMMIT_PATHS} arquivos por commit", status_code=400)
    rel_paths: list[str] = []
    root = _workspace_root(root_id)
    for raw in paths:
        p = (raw or "").strip()
        if not p:
            continue
        try:
            resolved = resolve_path(p)
        except WorkspaceError as exc:
            raise GitError(exc.message, status_code=exc.status_code) from exc
        rel_paths.append(resolved.relative_to(root).as_posix())
    if not rel_paths:
        raise GitError("Nenhum path válido", status_code=400)
    return rel_paths


def commit_changes(message: str, paths: list[str], root_id: str | None = None) -> dict[str, Any]:
    _ensure_repo(root_id)
    msg = _validate_commit_message(message)
    rel_paths = _validate_paths(paths, root_id)

    for rel in rel_paths:
        _run_git(root_id, "add", "--", rel)

    result = _run_git(root_id, "commit", "-m", msg)
    sha = ""
    for line in (result.stdout or "").splitlines():
        if line.startswith("[") and len(line) > 10:
            # [main abc1234] message
            parts = line.split()
            if len(parts) >= 2:
                sha = parts[1].rstrip("]")
            break

    return {
        "committed": True,
        "sha": sha,
        "paths": rel_paths,
        "message": msg,
    }


def get_git_summary() -> dict[str, Any]:
    from learning_agent.core.workspace_roots import list_roots

    summaries: list[dict[str, Any]] = []
    for root in list_roots():
        entry: dict[str, Any] = {
            "root_id": root["id"],
            "name": root.get("name") or root["id"],
            "git": bool(root.get("git")),
        }
        if not root.get("git"):
            summaries.append(entry)
            continue
        try:
            st = get_status(root["id"])
            entry.update(
                {
                    "branch": st["branch"],
                    "clean": st["clean"],
                    "dirty_count": sum(st.get("counts", {}).values()),
                }
            )
        except GitError as exc:
            entry["error"] = exc.message
        summaries.append(entry)
    return {"summaries": summaries}
