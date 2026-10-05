"""Safety guards and pre-flight helpers for Ravenna auto_apply."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from learning_agent.core import workspace

LARGE_FILE_LINE_THRESHOLD = 200
MIN_RETAINED_RATIO = 0.35
PREFLIGHT_MAX_LINES = 72
PREFLIGHT_MAX_BYTES = 24_000


def infer_patch_mode(text: str) -> bool:
    lowered = (text or "").lower()
    markers = (
        "patch cirúrgico",
        "patch cirurgico",
        "não substitua arquivos inteiros",
        "nao substitua arquivos inteiros",
        "não reescreva routes.py",
        "nao reescreva routes.py",
        "surgical patch",
        "menor conjunto de arquivos",
        "edições pontuais",
        "edicao pontual",
    )
    return any(token in lowered for token in markers)


def infer_flask_legacy(text: str) -> bool:
    lowered = (text or "").lower()
    return (
        "flask" in lowered
        or "remote_app/" in lowered
        or "notification_service.py" in lowered
        or "routes.py" in lowered and "tratativa" in lowered
    )


def infer_allowed_paths(text: str, required_files: list[str] | None = None) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"`([A-Za-z0-9_./\\-]+\.(?:py|html|js|css|tsx?|mjs))`", text or ""):
        candidate = match.group(1).replace("\\", "/").strip("/")
        if candidate.startswith(("a/", "b/")):
            continue
        if candidate and candidate not in paths:
            paths.append(candidate)
    for match in re.finditer(
        r"(?:^|\n)\s*[-*]\s+`?([A-Za-z0-9_./\\-]+\.(?:py|html|js|css|tsx?|mjs))`?",
        text or "",
        re.IGNORECASE,
    ):
        candidate = match.group(1).replace("\\", "/").strip("/")
        if candidate.startswith(("a/", "b/")):
            continue
        if candidate and candidate not in paths:
            paths.append(candidate)
    for file in required_files or []:
        normalized = file.replace("\\", "/").strip("/")
        if normalized.startswith(("a/", "b/")):
            continue
        if normalized and normalized not in paths:
            paths.append(normalized)
    return paths


def infer_locked_large_files(text: str) -> list[str]:
    locked: list[str] = []
    for match in re.finditer(
        r"`?([A-Za-z0-9_./\\-]+\.(?:py|html))`?\s*(?:tem|has|with)\s*~?\s*(\d+)\s*linhas",
        text or "",
        re.IGNORECASE,
    ):
        path = match.group(1).replace("\\", "/").strip("/")
        if int(match.group(2)) >= LARGE_FILE_LINE_THRESHOLD and path not in locked:
            locked.append(path)
    if "routes.py" in (text or "").lower() and "remote_app/routes.py" not in locked:
        locked.append("remote_app/routes.py")
    return locked


def _line_count(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def _normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def path_allowed(path: str, allowed_paths: list[str] | None) -> bool:
    if not allowed_paths:
        return True
    normalized = _normalize_rel(path)
    allowed = [_normalize_rel(item) for item in allowed_paths]
    return any(
        normalized == item
        or normalized.endswith(f"/{item}")
        or item.endswith(normalized)
        or (item and normalized.startswith(f"{item}/"))
        for item in allowed
    )


def should_block_write(
    relative_path: str,
    new_content: str,
    *,
    spec: dict[str, Any] | None = None,
    allowed_paths: list[str] | None = None,
) -> str | None:
    """Return human-readable reason when a write must be blocked."""
    spec = spec or {}
    rel = _normalize_rel(relative_path)

    from learning_agent.core import ravenna_home_delivery

    delivery_block = ravenna_home_delivery.should_block_write(rel, new_content, spec=spec)
    if delivery_block:
        return delivery_block

    forbidden = [_normalize_rel(item) for item in (spec.get("forbiddenPaths") or [])]
    for item in forbidden:
        if rel == item or rel.endswith(f"/{item}") or item.endswith(rel):
            if "package.json" in item:
                return f"Path `{rel}` bloqueado — não edite `package.json` (JSON estrito; build Docker falha)."
            return f"Path `{rel}` proibido neste projeto (use App.tsx, não App.js)."
    patch_mode = spec.get("patchMode") == "surgical"
    whitelist = allowed_paths or spec.get("allowedPaths") or []
    if spec.get("enforceAllowedPaths") and whitelist and not path_allowed(rel, whitelist):
        return f"Path `{rel}` fora do escopo permitido neste épico."
    locked = [_normalize_rel(item) for item in (spec.get("lockedFiles") or [])]
    new_lines = _line_count(new_content)
    trusted = bool(spec.get("trustedCanonical"))

    if patch_mode and whitelist and not path_allowed(rel, whitelist):
        return f"Path `{rel}` fora da whitelist cirúrgica."

    try:
        existing_path = workspace.resolve_path(relative_path)
    except workspace.WorkspaceError:
        existing_path = None

    if trusted and path_allowed(rel, whitelist or [rel]):
        return None

    if rel in locked or any(rel.endswith(f"/{item}") for item in locked):
        old_lines = 0
        if existing_path and existing_path.is_file():
            try:
                old_lines = _line_count(existing_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                old_lines = 0
        if old_lines >= LARGE_FILE_LINE_THRESHOLD:
            if new_lines < max(12, int(old_lines * 0.85)):
                return (
                    f"Arquivo protegido `{rel}` ({old_lines} linhas): conteúdo novo ({new_lines} linhas) "
                    "parece rewrite completo. Edite só o trecho necessário preservando o restante."
                )
        elif old_lines > 0 and new_lines < old_lines:
            return (
                f"Arquivo protegido `{rel}`: não reescreva sem incluir o conteúdo existente relevante."
            )

    if existing_path is None or not existing_path.is_file():
        return None

    try:
        old_text = existing_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if rel.endswith("notification_service.py") and not trusted:
        markers = (
            "TRATATIVA_TIPOS",
            "mark_tratativa_notifications_read",
            "comentario_id",
        )
        if all(marker in old_text for marker in markers):
            if new_lines < max(50, int(_line_count(old_text) * 0.8)):
                return (
                    "notification_service.py já conforme — write bloqueado "
                    "(conteúdo truncado ou rewrite completo)."
                )
            if not all(marker in new_content for marker in markers):
                return (
                    "notification_service.py já conforme — não sobrescrever com API inventada."
                )

    old_lines = _line_count(old_text)
    if old_lines < LARGE_FILE_LINE_THRESHOLD:
        return None

    if new_lines < max(8, int(old_lines * MIN_RETAINED_RATIO)):
        return (
            f"Write bloqueado em `{rel}`: conteúdo novo ({new_lines} linhas) "
            f"parece truncar arquivo existente ({old_lines} linhas). "
            "Faça patch cirúrgico preservando o restante."
        )

    old_bytes = len(old_text.encode("utf-8"))
    new_bytes = len(new_content.encode("utf-8"))
    if new_bytes < int(old_bytes * MIN_RETAINED_RATIO):
        return (
            f"Write bloqueado em `{rel}`: tamanho novo ({new_bytes} B) "
            f"muito menor que o existente ({old_bytes} B)."
        )

    return None


def build_preflight_context(
    paths: list[str],
    *,
    max_lines: int = PREFLIGHT_MAX_LINES,
    max_bytes: int = PREFLIGHT_MAX_BYTES,
) -> str:
    """Read target file heads so the model sees real symbols before writing."""
    if not paths:
        return ""

    chunks: list[str] = []
    for rel in paths:
        normalized = _normalize_rel(rel)
        try:
            data = workspace.read_file(normalized if "/" in normalized else rel)
        except workspace.WorkspaceError:
            chunks.append(f"### {normalized}\n(arquivo ausente ou ilegível)")
            continue

        content = data.get("content") or ""
        lines = content.splitlines()
        head = "\n".join(lines[:max_lines])
        truncated = len(lines) > max_lines or data.get("truncated")
        size = data.get("size") or len(content.encode("utf-8"))
        suffix = f"\n... [{len(lines)} linhas, {size} bytes total; mostrando {min(len(lines), max_lines)}]"
        if truncated:
            suffix += " (truncado pelo explorer)"
        chunks.append(f"### {data.get('path') or normalized}{suffix}\n```\n{head}\n```")

        if sum(len(part.encode("utf-8")) for part in chunks) > max_bytes:
            chunks.append("...(preflight truncado por limite de bytes)")
            break

    if not chunks:
        return ""

    return (
        "CONTEXTO PRÉ-VOO (leia antes de escrever; preserve arquivos grandes):\n"
        + "\n\n".join(chunks)
    )
