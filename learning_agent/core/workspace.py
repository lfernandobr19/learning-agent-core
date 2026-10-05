"""Leitura segura do workspace para o explorer da Ravenna IDE (multi-root)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

MAX_READ_BYTES = 512_000
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".cursor",
    "chroma",
}
SKIP_FILE_NAMES = {".env"}


class WorkspaceError(Exception):
    """Erro de acesso ao workspace (mapeado para HTTP na API)."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _legacy_workspace_root() -> Path:
    custom = os.environ.get("RAVENNA_WORKSPACE_ROOT", "").strip()
    root = Path(custom).resolve() if custom else PROJECT_ROOT.resolve()
    if not root.is_dir():
        raise WorkspaceError("Workspace root inválido", status_code=500)
    return root


def _split_workspace_path(relative: str) -> tuple[str | None, str]:
    """Retorna (root_id, inner_path). root_id None = workspace principal."""
    from learning_agent.core.workspace_roots import (
        canonical_workspace_ref,
        find_root,
        get_primary_root,
    )

    rel = canonical_workspace_ref(relative or "")
    if not rel:
        return None, ""

    first = rel.split("/", 1)[0]
    if find_root(first):
        inner = rel.split("/", 1)[1] if "/" in rel else ""
        return first, inner

    primary = get_primary_root()
    if first == primary["id"]:
        inner = rel.split("/", 1)[1] if "/" in rel else ""
        return primary["id"], inner

    return None, rel


def _root_path(root_id: str | None) -> Path:
    from learning_agent.core.workspace_roots import WorkspaceRootsError, get_root_path

    try:
        return get_root_path(root_id)
    except WorkspaceRootsError as exc:
        raise WorkspaceError(exc.message, status_code=exc.status_code) from exc


def resolve_path(relative: str = "") -> Path:
    """Resolve caminho relativo dentro de um workspace root; bloqueia path traversal."""
    root_id, inner = _split_workspace_path(relative)
    root = _root_path(root_id)

    rel = inner.replace("\\", "/").strip("/")
    if rel and ".." in Path(rel).parts:
        raise WorkspaceError("Path inválido", status_code=400)

    target = (root / rel).resolve() if rel else root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Path fora do workspace", status_code=403) from exc
    return target


def _canonical_path(root_id: str, inner: str) -> str:
    inner = inner.replace("\\", "/").strip("/")
    return root_id if not inner else f"{root_id}/{inner}"


def _list_dir_in_root(root_id: str, inner: str) -> dict[str, Any]:
    root = _root_path(root_id)
    rel_inner = inner.replace("\\", "/").strip("/")
    path = (root / rel_inner).resolve() if rel_inner else root.resolve()

    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Path fora do workspace", status_code=403) from exc

    if not path.exists():
        raise WorkspaceError("Diretório não encontrado", status_code=404)
    if not path.is_dir():
        raise WorkspaceError("Não é um diretório", status_code=400)

    entries: list[dict[str, Any]] = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise WorkspaceError(f"Sem permissão de leitura: {exc}", status_code=403) from exc

    for child in children:
        name = child.name
        if name.startswith("."):
            continue
        if child.is_dir() and name in SKIP_DIR_NAMES:
            continue
        if child.is_file() and name in SKIP_FILE_NAMES:
            continue

        child_inner = child.relative_to(root).as_posix()
        canonical = _canonical_path(root_id, child_inner)
        entry: dict[str, Any] = {
            "name": name,
            "path": canonical,
            "type": "dir" if child.is_dir() else "file",
            "root_id": root_id,
        }
        if child.is_file():
            try:
                entry["size"] = child.stat().st_size
            except OSError:
                entry["size"] = 0
        entries.append(entry)

    from learning_agent.core.workspace_roots import find_root

    root_meta = find_root(root_id) or {"name": root.name}
    return {
        "root": root_meta.get("name", root.name),
        "root_id": root_id,
        "path": _canonical_path(root_id, rel_inner) if rel_inner else root_id,
        "multi_root": True,
        "entries": entries,
    }


def list_directory(relative: str = "") -> dict[str, Any]:
    """Lista entradas de um diretório (não recursivo). Com multi-root, path vazio lista roots."""
    from learning_agent.core.workspace_roots import (
        find_root,
        get_primary_root,
        list_roots,
    )

    rel = (relative or "").strip().replace("\\", "/").strip("/")
    roots = list_roots()

    if not rel:
        if len(roots) <= 1:
            primary = get_primary_root()
            return _list_dir_in_root(primary["id"], "")

        return {
            "root": "workspaces",
            "path": "",
            "multi_root": True,
            "entries": [
                {
                    "name": r["name"],
                    "path": r["id"],
                    "type": "root",
                    "root_id": r["id"],
                    "kind": r.get("kind", "folder"),
                    "git": r.get("git", False),
                    "git_remote": r.get("git_remote"),
                }
                for r in roots
            ],
        }

    first = rel.split("/", 1)[0]
    root = find_root(first)
    if root:
        inner = rel.split("/", 1)[1] if "/" in rel else ""
        return _list_dir_in_root(root["id"], inner)

    primary = get_primary_root()
    return _list_dir_in_root(primary["id"], rel)


def read_file(relative: str) -> dict[str, Any]:
    """Lê conteúdo textual de um arquivo do workspace."""
    if not relative or not relative.strip():
        raise WorkspaceError("Path obrigatório", status_code=400)

    root_id, inner = _split_workspace_path(relative)
    if root_id is None:
        from learning_agent.core.workspace_roots import get_primary_root

        root_id = get_primary_root()["id"]

    path = resolve_path(relative)
    if not path.exists():
        raise WorkspaceError("Arquivo não encontrado", status_code=404)
    if not path.is_file():
        raise WorkspaceError("Não é um arquivo", status_code=400)
    if path.name in SKIP_FILE_NAMES:
        raise WorkspaceError("Arquivo não permitido", status_code=403)

    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise WorkspaceError(
            f"Arquivo muito grande (máx {MAX_READ_BYTES // 1024} KB)",
            status_code=413,
        )

    try:
        content = path.read_text(encoding="utf-8")
        encoding = "utf-8"
        truncated = False
    except UnicodeDecodeError:
        raw = path.read_bytes()
        content = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        encoding = "binary"
        truncated = len(raw) > MAX_READ_BYTES

    root = _root_path(root_id)
    inner_path = path.relative_to(root).as_posix()
    return {
        "path": _canonical_path(root_id, inner_path),
        "name": path.name,
        "size": size,
        "encoding": encoding,
        "truncated": truncated,
        "writable": encoding == "utf-8" and not truncated,
        "content": content,
        "root_id": root_id,
    }


def write_file(relative: str, content: str) -> dict[str, Any]:
    """Grava conteúdo UTF-8 em arquivo do workspace."""
    if not relative or not relative.strip():
        raise WorkspaceError("Path obrigatório", status_code=400)

    if len(content.encode("utf-8")) > MAX_READ_BYTES:
        raise WorkspaceError(
            f"Conteúdo muito grande (máx {MAX_READ_BYTES // 1024} KB)",
            status_code=413,
        )

    root_id, _ = _split_workspace_path(relative)
    if root_id is None:
        from learning_agent.core.workspace_roots import get_primary_root

        root_id = get_primary_root()["id"]

    path = resolve_path(relative)
    if path.name in SKIP_FILE_NAMES:
        raise WorkspaceError("Arquivo não permitido", status_code=403)

    root = _root_path(root_id)
    if not path.exists():
        parent = path.parent
        try:
            parent.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError("Path fora do workspace", status_code=403) from exc
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(f"Falha ao criar diretório pai: {exc}", status_code=500) from exc
    elif not path.is_file():
        raise WorkspaceError("Não é um arquivo", status_code=400)

    try:
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise WorkspaceError(f"Falha ao gravar: {exc}", status_code=500) from exc

    inner_path = path.relative_to(root).as_posix()
    size = path.stat().st_size
    result = {
        "path": _canonical_path(root_id, inner_path),
        "name": path.name,
        "size": size,
        "saved": True,
        "root_id": root_id,
    }
    try:
        from learning_agent.core import remote_live

        live = remote_live.mirror_after_local_write(root_id, inner_path, content)
        if live:
            result["remote_live"] = live
    except remote_live.RemoteLiveError as exc:
        raise WorkspaceError(
            f"Gravou no cache local, mas falhou no servidor remoto: {exc.message}",
            status_code=exc.status_code,
        ) from exc
    return result


def delete_file(relative: str) -> dict[str, Any]:
    """Remove arquivo do workspace com as mesmas garantias de path traversal."""
    if not relative or not relative.strip():
        raise WorkspaceError("Path obrigatório", status_code=400)

    root_id, _ = _split_workspace_path(relative)
    if root_id is None:
        from learning_agent.core.workspace_roots import get_primary_root

        root_id = get_primary_root()["id"]

    path = resolve_path(relative)
    if path.name in SKIP_FILE_NAMES:
        raise WorkspaceError("Arquivo não permitido", status_code=403)
    if not path.exists():
        return {"path": relative.replace("\\", "/"), "deleted": False, "root_id": root_id}
    if not path.is_file():
        raise WorkspaceError("Não é um arquivo", status_code=400)

    root = _root_path(root_id)
    inner_path = path.relative_to(root).as_posix()
    try:
        path.unlink()
    except OSError as exc:
        raise WorkspaceError(f"Falha ao remover: {exc}", status_code=500) from exc

    return {
        "path": _canonical_path(root_id, inner_path),
        "deleted": True,
        "root_id": root_id,
    }
