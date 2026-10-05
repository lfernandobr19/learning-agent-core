"""Registro de workspaces multi-root para a Ravenna IDE."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR, PROJECT_ROOT

REGISTRY_PATH = DATA_DIR / "ide-workspace-roots.json"
EXTERNAL_REPOS_DIR = DATA_DIR / "external-repos"


class WorkspaceRootsError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _normalize_stored_path(stored: str) -> Path:
    """Map Windows registry paths to Linux/Docker PROJECT_ROOT when needed."""
    raw = stored.strip()
    if not raw:
        return _default_primary_path()

    if os.name != "nt" and (len(raw) > 1 and raw[1] == ":" or raw.startswith("\\\\")):
        norm = raw.replace("\\", "/").lower()
        root = PROJECT_ROOT.resolve()
        data = (root / "data").resolve()
        if "/external-repos/financeiro" in norm:
            return (data / "external-repos" / "financeiro").resolve()
        if "/remote-workspaces/" in norm:
            tail = norm.split("/remote-workspaces/", 1)[1].strip("/")
            return (data / "remote-workspaces" / tail.replace("/", os.sep)).resolve()
        if "learning-agent/learning-agent" in norm or norm.endswith("/learning-agent"):
            return root
        if "/ravenna-home" in norm or norm.endswith("ravenna-home"):
            candidate = root / "ravenna-home"
            if candidate.is_dir():
                return candidate.resolve()
            fallback = Path("/app/ravenna-home")
            if fallback.is_dir():
                return fallback.resolve()
        return root

    return Path(raw).expanduser().resolve()


def _default_primary_path() -> Path:
    custom = os.environ.get("RAVENNA_WORKSPACE_ROOT", "").strip()
    return Path(custom).resolve() if custom else PROJECT_ROOT.resolve()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", name.strip()).strip("-").lower()
    return slug or "workspace"


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _normalize_git_url(url: str) -> str:
    raw = url.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", raw):
        return f"https://github.com/{raw}.git"
    if raw.startswith("github:"):
        return f"https://github.com/{raw.removeprefix('github:').strip('/')}.git"
    if raw.startswith("https://github.com/") and not raw.endswith(".git"):
        return raw.rstrip("/") + ".git"
    if raw.startswith(("https://", "http://", "git@", "ssh://")):
        return raw
    raise WorkspaceRootsError("Use uma URL Git válida ou o formato org/repo do GitHub", status_code=400)


def _git_remote(path: Path) -> str | None:
    if not _is_git_repo(path):
        return None
    git = shutil.which("git")
    if not git:
        return None
    try:
        proc = subprocess.run(
            [git, "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _load_raw() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        primary_path = _default_primary_path()
        return {
            "version": 1,
            "primary_id": _slugify(primary_path.name),
            "roots": [
                {
                    "id": _slugify(primary_path.name),
                    "name": primary_path.name,
                    "path": str(primary_path),
                    "kind": "primary",
                    "git": _is_git_repo(primary_path),
                    "git_remote": _git_remote(primary_path),
                }
            ],
        }
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceRootsError(f"Registry inválido: {exc}", status_code=500) from exc
    if not isinstance(data.get("roots"), list):
        raise WorkspaceRootsError("Registry inválido: roots ausente", status_code=500)
    return data


def _save_raw(data: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _unique_id(base: str, existing: set[str]) -> str:
    slug = _slugify(base)
    if slug not in existing:
        return slug
    i = 2
    while f"{slug}-{i}" in existing:
        i += 1
    return f"{slug}-{i}"


def list_roots() -> list[dict[str, Any]]:
    data = _load_raw()
    roots: list[dict[str, Any]] = []
    for root in data["roots"]:
        path = _normalize_stored_path(str(root["path"]))
        entry = dict(root)
        entry["path"] = str(path)
        entry["exists"] = path.is_dir()
        entry["git"] = _is_git_repo(path)
        remote = _git_remote(path)
        if remote:
            entry["git_remote"] = remote
        roots.append(entry)
    return roots


def _kind_rank(kind: str) -> int:
    order = {"primary": 0, "folder": 1, "git": 2, "remote-cache": 3, "remote-live": 4}
    return order.get(kind, 5)


def _root_ui_score(root: dict[str, Any]) -> tuple[int, int, int, str]:
    """Lower tuple wins when picking the canonical root for UI dedupe."""
    exists_rank = 0 if root.get("exists") else 1
    root_id = str(root.get("id") or "")
    suffix_penalty = 1 if re.search(r"-\d+$", root_id) else 0
    kind_rank = _kind_rank(str(root.get("kind") or "folder"))
    return (exists_rank, suffix_penalty, kind_rank, root_id)


def list_roots_for_ui() -> list[dict[str, Any]]:
    """Deduplicate registry entries that share the same display name (host vs container paths)."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for root in list_roots():
        key = str(root.get("name") or root.get("id") or "").strip().casefold()
        if not key:
            key = str(root.get("id") or "")
        grouped.setdefault(key, []).append(root)

    visible: list[dict[str, Any]] = []
    for _key, items in grouped.items():
        winner = min(items, key=_root_ui_score)
        visible.append(dict(winner))
    visible.sort(key=lambda r: (str(r.get("name") or "").casefold(), str(r.get("id") or "")))
    return visible


def get_primary_root() -> dict[str, Any]:
    data = _load_raw()
    primary_id = data.get("primary_id")
    for root in list_roots():
        if root["id"] == primary_id:
            return root
    return list_roots()[0]


def find_root(root_id: str) -> dict[str, Any] | None:
    if not root_id:
        return None
    for root in list_roots():
        if root["id"] == root_id:
            return root
    return None


def _project_relative_posix(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _root_registry_tail(root: dict[str, Any]) -> str | None:
    stored = str(root.get("path") or "").strip()
    if not stored:
        return None
    normalized = _normalize_stored_path(stored)
    tail = _project_relative_posix(normalized)
    if tail:
        return tail
    posix = normalized.as_posix().strip("/")
    for marker in ("data/remote-workspaces/", "data/external-repos/"):
        idx = posix.find(marker)
        if idx >= 0:
            return posix[idx:]
    return None


def canonical_workspace_ref(relative: str) -> str:
    """Map legacy relative paths (e.g. data/remote-workspaces/remote_app-teste) to root ids."""
    rel = (relative or "").strip().replace("\\", "/").strip("/")
    if not rel:
        return ""

    first = rel.split("/", 1)[0]
    if find_root(first):
        return rel

    for root in list_roots():
        tail = _root_registry_tail(root)
        if not tail:
            continue
        if rel == tail or rel.startswith(f"{tail}/"):
            inner = rel[len(tail) :].strip("/") if rel != tail else ""
            return root["id"] if not inner else f"{root['id']}/{inner}"

    return rel


def get_root_path(root_id: str | None = None) -> Path:
    if root_id:
        root = find_root(root_id)
        if not root:
            raise WorkspaceRootsError(f"Workspace '{root_id}' não encontrado", status_code=404)
        path = _normalize_stored_path(str(root["path"]))
    else:
        path = _normalize_stored_path(str(get_primary_root()["path"]))
    if not path.is_dir():
        # VM: primary inexistente ou pc-workspace vazio → repo real no container
        fallback = Path("/app")
        if fallback.is_dir():
            posix = path.as_posix()
            if posix == "/app/pc-workspace" or "pc-workspace" in posix or not path.exists():
                return fallback
        raise WorkspaceRootsError(f"Diretório do workspace não existe: {path}", status_code=404)
    return path


def add_folder_root(abs_path: str, *, name: str | None = None) -> dict[str, Any]:
    path = Path(abs_path).expanduser().resolve()
    if not path.is_dir():
        raise WorkspaceRootsError("Caminho não é um diretório válido", status_code=400)

    data = _load_raw()
    existing_paths = {Path(r["path"]).resolve() for r in data["roots"]}
    if path in existing_paths:
        raise WorkspaceRootsError("Este diretório já está anexado", status_code=409)

    ids = {r["id"] for r in data["roots"]}
    root_id = _unique_id(name or path.name, ids)
    entry = {
        "id": root_id,
        "name": name or path.name,
        "path": str(path),
        "kind": "git" if _is_git_repo(path) else "folder",
        "git": _is_git_repo(path),
        "git_remote": _git_remote(path),
    }
    data["roots"].append(entry)
    _save_raw(data)
    return entry


def add_git_repo(url: str, *, name: str | None = None, branch: str | None = None) -> dict[str, Any]:
    raw_url = url.strip()
    if not raw_url:
        raise WorkspaceRootsError("URL do repositório obrigatória", status_code=400)
    url = _normalize_git_url(raw_url)

    git = shutil.which("git")
    if not git:
        raise WorkspaceRootsError("Git não encontrado no PATH", status_code=503)

    base_name = name or url.rstrip("/").split("/")[-1].replace(".git", "")
    slug = _slugify(base_name)
    EXTERNAL_REPOS_DIR.mkdir(parents=True, exist_ok=True)
    target = EXTERNAL_REPOS_DIR / slug
    if target.exists():
        raise WorkspaceRootsError(f"Destino já existe: {target}", status_code=409)

    cmd = [git, "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([url, str(target)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceRootsError("Timeout ao clonar repositório", status_code=504) from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "falha desconhecida").strip()
        raise WorkspaceRootsError(f"Falha ao clonar: {err}", status_code=400)

    return add_folder_root(str(target), name=base_name)


def remove_root(root_id: str) -> None:
    data = _load_raw()
    if root_id == data.get("primary_id"):
        raise WorkspaceRootsError("Não é possível remover o workspace principal", status_code=400)
    before = len(data["roots"])
    data["roots"] = [r for r in data["roots"] if r["id"] != root_id]
    if len(data["roots"]) == before:
        raise WorkspaceRootsError(f"Workspace '{root_id}' não encontrado", status_code=404)
    _save_raw(data)


def discover_git_repos(parent_path: str | None = None, *, limit: int = 24) -> list[dict[str, Any]]:
    """Lista repositórios git irmãos (ex.: pasta RAVENNA) ainda não anexados."""
    if parent_path:
        parent = Path(parent_path).expanduser().resolve()
    else:
        env_parent = os.environ.get("RAVENNA_WORKSPACE_PARENT", "").strip()
        if env_parent:
            parent = Path(env_parent).expanduser().resolve()
        else:
            parent = _default_primary_path().parent

    if not parent.is_dir():
        raise WorkspaceRootsError("Pasta pai inválida", status_code=400)

    attached = {Path(r["path"]).resolve() for r in list_roots()}
    found: list[dict[str, Any]] = []

    try:
        children = sorted(parent.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise WorkspaceRootsError(f"Sem permissão para ler {parent}", status_code=403) from exc

    for child in children:
        if len(found) >= limit:
            break
        if not child.is_dir() or child.name.startswith("."):
            continue
        resolved = child.resolve()
        if resolved in attached:
            continue
        if _is_git_repo(resolved):
            found.append(
                {
                    "name": child.name,
                    "path": str(resolved),
                    "git_remote": _git_remote(resolved),
                }
            )
    return found


HOST_MIRROR = Path("/host")
_HOST_VIRT_SKIP = {"proc", "sys", "dev"}


def _host_mirror_available() -> bool:
    try:
        return HOST_MIRROR.is_dir()
    except OSError:
        return False


def _to_container_path(raw: str) -> Path:
    """Traduz um caminho do host (ex. /home/<user>/projects) para o que o container enxerga.

    Sem o bind `/:/host`, o backend só vê o filesystem do container. Com o espelho,
    o mesmo caminho do servidor vira `/host/...` e a IDE consegue abrir.
    """
    text = (raw or "").strip() or "~"
    if text in ("~", ""):
        candidate = Path.home()
    else:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path.home() / candidate

    try:
        if candidate.exists():
            return candidate.resolve()
    except OSError:
        pass

    if _host_mirror_available():
        mirrored = HOST_MIRROR.joinpath(*candidate.parts[1:]) if candidate.is_absolute() else HOST_MIRROR / candidate
        try:
            if mirrored.exists():
                return mirrored.resolve()
        except OSError:
            pass
        return mirrored

    try:
        return candidate.resolve()
    except OSError:
        return candidate


def _allowed_browse_roots() -> tuple[Path, ...]:
    """Pastas que a IDE pode listar no browser (API sem display)."""
    items: list[Path] = [
        PROJECT_ROOT.resolve(),
        DATA_DIR.resolve(),
        Path.home().resolve(),
    ]
    for key in ("RAVENNA_WORKSPACE_PARENT", "RAVENNA_WORKSPACE_ROOT"):
        val = os.environ.get(key, "").strip()
        if val:
            items.append(Path(val).expanduser().resolve())
    extras = ["/app", "/app/pc-workspace", "/home/lfernando"]
    if _host_mirror_available():
        extras.append(str(HOST_MIRROR))
    for extra in extras:
        p = Path(extra)
        try:
            if p.is_dir():
                items.append(p.resolve())
        except OSError:
            continue
    if os.name == "nt":
        import string

        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            try:
                if drive.is_dir():
                    items.append(drive.resolve())
            except OSError:
                continue
    seen: set[str] = set()
    out: list[Path] = []
    for path in items:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return tuple(out)


def _is_under_allowed_browse_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _allowed_browse_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _browse_shortcuts() -> list[tuple[str, Path]]:
    shortcuts: list[tuple[str, Path]] = []
    home = Path.home()
    if home.is_dir():
        shortcuts.append(("Home", home.resolve()))
    project = PROJECT_ROOT.resolve()
    shortcuts.append(("learning-agent", project))
    data = DATA_DIR.resolve()
    if data.is_dir() and data != project:
        shortcuts.append(("data/", data))
    pc = Path("/app/pc-workspace")
    if pc.is_dir():
        shortcuts.append(("PC workspace", pc.resolve()))
    if _host_mirror_available():
        shortcuts.append(("Servidor", HOST_MIRROR.resolve()))
        host_home = HOST_MIRROR / "home" / "lfernando"
        if host_home.is_dir():
            shortcuts.append(("Home do servidor", host_home.resolve()))
        remote_app = host_home / "REMOTE_APP"
        if remote_app.is_dir():
            shortcuts.append(("RemoteApp", remote_app.resolve()))
    parent = os.environ.get("RAVENNA_WORKSPACE_PARENT", "").strip()
    if parent:
        pp = Path(parent).expanduser()
        if pp.is_dir():
            shortcuts.append(("Workspace parent", pp.resolve()))
    return shortcuts


def browse_local_directory(path: str = "~") -> dict[str, Any]:
    """Lista diretórios acessíveis no servidor para o seletor de pasta da IDE."""
    allowed_roots = [
        {"label": label, "path": str(p.resolve())}
        for label, p in _browse_shortcuts()
        if p.is_dir()
    ]

    raw = (path or "~").strip() or "~"
    current = _to_container_path(raw)

    if not _is_under_allowed_browse_root(current):
        raise WorkspaceRootsError(
            "Fora das pastas acessíveis no servidor — use os atalhos abaixo ou cole um caminho válido.",
            status_code=403,
        )
    if not current.exists():
        raise WorkspaceRootsError("Caminho não existe", status_code=404)
    if not current.is_dir():
        raise WorkspaceRootsError("Não é um diretório", status_code=400)

    parent = ""
    parent_path = current.parent.resolve()
    if parent_path != current and _is_under_allowed_browse_root(parent_path):
        parent = str(parent_path)

    try:
        children = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError as exc:
        raise WorkspaceRootsError(f"Sem permissão para ler {current}", status_code=403) from exc

    entries: list[dict[str, str]] = []
    filtered_count = 0
    for child in children:
        if child.name.startswith("."):
            filtered_count += 1
            continue
        if current == HOST_MIRROR and child.name in _HOST_VIRT_SKIP:
            filtered_count += 1
            continue
        try:
            resolved = child.resolve()
        except OSError:
            filtered_count += 1
            continue
        if not _is_under_allowed_browse_root(resolved):
            filtered_count += 1
            continue
        kind = "dir" if resolved.is_dir() else "file"
        entries.append({"name": child.name, "path": str(resolved), "kind": kind})

    shortcuts = [{"label": label, "path": str(p)} for label, p in _browse_shortcuts()]
    return {
        "ok": True,
        "path": str(current),
        "parent": parent,
        "entries": entries,
        "shortcuts": shortcuts,
        "allowed_roots": allowed_roots,
        "filtered_count": filtered_count,
    }


def pick_folder_dialog() -> str | None:
    """Abre seletor nativo de pasta (Windows/macOS/Linux) — só funciona com API local e display."""
    if not os.environ.get("DISPLAY", "").strip() and os.name != "nt":
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askdirectory(title="Selecionar pasta do projeto")
        root.destroy()
        return path.strip() if path else None
    except Exception:
        return None


def _pc_workspace_windows_root() -> str:
    """Raiz do workspace do PC (caminho Windows) usada para mapear pastas escolhidas no Explorer."""
    val = os.environ.get("RAVENNA_PC_WORKSPACE", "").strip()
    if val:
        return val
    # Fallback para o setup do Luis (synced para /app/pc-workspace na VM).
    return r"C:\Users\lfern\RAVENNA\learning-agent\learning-agent"


def map_local_folder(local_path: str) -> dict[str, Any]:
    """Converte um caminho vindo do explorador nativo (Electron/Windows) num caminho de servidor.

    - API local no Windows: o caminho já é válido no filesystem → is_local=True.
    - API remota (VM/container): espelha sob /app/pc-workspace:
      - dentro do workspace do PC → /app/pc-workspace/<rel>
      - qualquer outra pasta → /app/pc-workspace/_drives/<drive>/<rest>
    Retorna também `source` (caminho Windows real a sincronizar) quando for pasta
    fora do espelho padrão, para o sync on-demand disparar o espelhamento correto.
    """
    raw = (local_path or "").strip().strip('"').strip("'")
    if not raw:
        raise WorkspaceRootsError("Caminho vazio", status_code=400)

    if os.name == "nt":
        try:
            resolved = Path(raw).expanduser().resolve()
        except OSError as exc:
            raise WorkspaceRootsError(f"Caminho inválido: {exc}", status_code=400) from exc
        return {"ok": True, "server_path": str(resolved), "is_local": True, "needs_sync": False}

    win_root = _pc_workspace_windows_root().replace("\\", "/").rstrip("/")
    norm = raw.replace("\\", "/").strip("/")
    win_root_low = win_root.lower()
    norm_low = norm.lower()

    if norm_low == win_root_low or norm_low.startswith(win_root_low + "/"):
        # Dentro do espelho do workspace do PC → /app/pc-workspace/<rel>
        rel = norm[len(win_root):].lstrip("/")
        server_path = f"/app/pc-workspace/{rel}" if rel else "/app/pc-workspace"
        exists = Path(server_path).is_dir()
        return {
            "ok": True,
            "server_path": server_path,
            "is_local": False,
            "needs_sync": not exists,
            "relative": rel,
            "source": None,
        }

    # Qualquer outra pasta do PC → espelho sob /app/pc-workspace/_drives/<drive>/<rest>
    m = re.match(r"^([a-zA-Z]):(?:/(.*))?$", norm)
    if not m:
        raise WorkspaceRootsError(
            "Caminho não reconhecido — informe um caminho absoluto do Windows "
            "(ex.: C:\\Projetos\\meu-app). Caminhos UNC não são suportados.",
            status_code=400,
        )
    drive = m.group(1).lower()
    rest = (m.group(2) or "").strip("/")
    rel = f"_drives/{drive}/{rest}" if rest else f"_drives/{drive}"
    server_path = f"/app/pc-workspace/{rel}"
    exists = Path(server_path).is_dir()
    return {
        "ok": True,
        "server_path": server_path,
        "is_local": False,
        "needs_sync": not exists,
        "relative": rel,
        "source": raw,
    }

