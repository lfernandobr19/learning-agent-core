"""Investigação automática antes do LLM — Fase 2 (evidências no prompt)."""

from __future__ import annotations

import re
from typing import Any

from learning_agent.core import agent_spec_builder, autonomy_guards, codebase, context, errors, workspace

_PATH_RE = re.compile(
    r"(?:^|[\s`'\"(])([a-zA-Z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|css|html|yaml|yml|md|json))(?:[\s`'\"),]|$)",
    re.MULTILINE,
)
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{2,}")


def infer_paths_from_message(message: str, spec: dict[str, Any] | None = None) -> list[str]:
    """Extrai paths prováveis da mensagem + spec."""
    paths: list[str] = []
    spec = spec or {}
    for raw in (spec.get("requiredFiles") or []) + (spec.get("allowedPaths") or []):
        p = str(raw).replace("\\", "/").strip("/")
        if p and p not in paths:
            paths.append(p)
    for match in _PATH_RE.finditer(message or ""):
        p = match.group(1).replace("\\", "/").strip("/")
        if p and p not in paths:
            paths.append(p)
    return paths[:12]


def _grep_workspace(pattern: str, *, path_prefix: str = "", max_hits: int = 8) -> list[dict[str, str]]:
    if not pattern.strip():
        return []
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return [{"path": "", "line": "", "text": f"regex inválido: {pattern}"}]
    hits: list[dict[str, str]] = []
    start = path_prefix.replace("\\", "/").strip("/")
    try:
        listing = workspace.list_directory(start)
    except workspace.WorkspaceError:
        return hits
    stack = [(start, listing.get("entries") or [])]
    while stack and len(hits) < max_hits:
        prefix, entries = stack.pop()
        for entry in entries:
            name = entry.get("name") or ""
            rel = f"{prefix}/{name}".strip("/") if prefix else name
            if entry.get("type") == "dir":
                if name in {".git", "node_modules", ".venv", "__pycache__"}:
                    continue
                try:
                    sub = workspace.list_directory(rel)
                    stack.append((rel, sub.get("entries") or []))
                except workspace.WorkspaceError:
                    continue
                continue
            if not re.search(r"\.(py|ts|tsx|js|jsx|css|html|md|yaml|yml)$", name, re.I):
                continue
            try:
                data = workspace.read_file(rel)
            except workspace.WorkspaceError:
                continue
            for i, line in enumerate((data.get("content") or "").splitlines(), 1):
                if regex.search(line):
                    hits.append({"path": rel, "line": str(i), "text": line.strip()[:200]})
                    if len(hits) >= max_hits:
                        break
    return hits


def build_investigation_context(
    message: str,
    spec: dict[str, Any] | None = None,
    *,
    project_root: str | None = None,
    max_bytes: int = 24_000,
) -> str:
    """Monta bloco EVIDÊNCIAS para o prompt do agente."""
    spec = spec or agent_spec_builder.build_spec(message, project_root=project_root)
    root = (project_root or spec.get("projectRoot") or "").replace("\\", "/").strip("/")
    paths = infer_paths_from_message(message, spec)
    if root:
        from learning_agent.core.workspace_bootstrap import scope_to_project_root

        scoped = [scope_to_project_root(root, p) for p in paths]
        paths = list(dict.fromkeys(scoped))[:10]

    chunks: list[str] = []
    if spec.get("ravennaHome"):
        from learning_agent.core.workspace_bootstrap import build_file_existence_grounding

        chunks.append(build_file_existence_grounding(project_root or spec.get("projectRoot")))
    chunks.append("EVIDÊNCIAS DA INVESTIGAÇÃO (backend — use no Diagnóstico):")

    # Pré-voo de arquivos
    if paths:
        preflight = autonomy_guards.build_preflight_context(paths[:6], max_lines=40)
        if preflight:
            chunks.append(preflight)

    # Busca semântica no código
    query_terms = " ".join(_TOKEN_RE.findall(message or "")[:8])
    if query_terms:
        try:
            code_hits = codebase.search_code(query_terms, limit=4)
            if code_hits:
                lines = ["### search_code"]
                for hit in code_hits:
                    meta = hit.get("metadata") or {}
                    src = meta.get("source") or meta.get("path") or "?"
                    sym = meta.get("symbol") or ""
                    snippet = (hit.get("content") or hit.get("document") or "")[:400]
                    lines.append(f"- `{src}` {sym}: {snippet[:200]}...")
                chunks.append("\n".join(lines))
        except Exception:
            pass

    # Contexto RAG agregado
    try:
        ctx = context.get_context_for_task(message, limit=3)
        if ctx:
            brief: list[str] = ["### get_context_for_task"]
            for item in (ctx.get("knowledge") or [])[:2]:
                brief.append(f"- [nota] {(item.get('content') or '')[:250]}")
            for item in (ctx.get("code") or [])[:1]:
                brief.append(f"- [code] {(item.get('content') or '')[:250]}")
            for err in (ctx.get("past_errors") or [])[:1]:
                brief.append(f"- [erro passado] {err.get('context', '')}: {(err.get('error') or '')[:120]}")
            if len(brief) > 1:
                chunks.append("\n".join(brief))
    except Exception:
        pass

    # Erros relacionados
    try:
        related = errors.get_related_errors(message, limit=3)
        if related:
            lines = ["### get_related_errors"]
            for err in related:
                lines.append(f"- {err.get('context', '?')}: {(err.get('error') or '')[:150]}")
            chunks.append("\n".join(lines))
    except Exception:
        pass

    # Grep por termos-chave da mensagem
    grep_terms: list[str] = []
    lower = (message or "").lower()
    for term in ("tratativa", "neon", "remote_app-notifications", "llm.py", "autonomy", "patch"):
        if term in lower:
            grep_terms.append(term)
    for term in grep_terms[:3]:
        hits = _grep_workspace(re.escape(term), max_hits=4)
        if hits:
            lines = [f"### grep `{term}`"]
            for h in hits:
                lines.append(f"- {h['path']}:{h['line']} — {h['text']}")
            chunks.append("\n".join(lines))

    body = "\n\n".join(chunks)
    if len(body.encode("utf-8")) > max_bytes:
        body = body[: max_bytes - 80] + "\n...(investigação truncada por limite)"
    return body if len(chunks) > 1 else ""
