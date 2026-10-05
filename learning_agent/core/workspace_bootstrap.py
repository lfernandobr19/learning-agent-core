"""Bootstrap de workspace multi-root — garante que projetos satélite (Ravenna Home) sejam visíveis."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT

_ABSENT_CLAIM_RE = re.compile(
    r"\b(ausente|ausentes|não exist|nao exist|não possui|nao possui|"
    r"não encontr|nao encontr|faltam|falta|missing|inexistente|"
    r"está ausente|esta ausente|preciso criar|precisamos criar|"
    r"vou criar|vamos criar|não há|nao ha)\b",
    re.IGNORECASE,
)

_SCOPE_DEVIATION_RE = re.compile(
    r"\b(pytest|py -m pytest|backend/tests|backend/main\.py|módulo pytest|modulo pytest)\b",
    re.IGNORECASE,
)

_VOICE_PWA_REQUIRED_READS = (
    "package.json",
    "src/components/Chat.tsx",
    "src/components/InstallPrompt.tsx",
    "public/manifest.webmanifest",
    "index.html",
)


def ravenna_home_dir() -> Path:
    """Diretório raiz do monorepo Ravenna Home (PC ou container Docker)."""
    custom = os.environ.get("RAVENNA_HOME_ROOT", "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    for candidate in (PROJECT_ROOT / "ravenna-home", Path("/app/ravenna-home")):
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return (PROJECT_ROOT / "ravenna-home").resolve()


def scope_to_project_root(project_root: str | None, relative: str) -> str:
    """Mapeia path relativo do agente para ref canônica no workspace (sem `frontend/frontend`)."""
    from learning_agent.core.workspace_roots import canonical_workspace_ref

    root = (project_root or "").replace("\\", "/").strip("/")
    rel = (relative or "").replace("\\", "/").strip("/")
    if not rel:
        return canonical_workspace_ref(root)
    if root and (rel == root or rel.startswith(f"{root}/")):
        return canonical_workspace_ref(rel)
    if root:
        root_tail = root.rsplit("/", 1)[-1]
        if rel == root_tail or rel.startswith(f"{root_tail}/"):
            rel = rel[len(root_tail) :].strip("/")
    scoped = f"{root}/{rel}" if root else rel
    return canonical_workspace_ref(scoped)


def ensure_ravenna_home_root() -> dict[str, Any] | None:
    """Registra `ravenna-home` em ide-workspace-roots.json se o diretório existir."""
    from learning_agent.core import workspace_roots

    home = ravenna_home_dir()
    if not home.is_dir():
        return None

    existing = workspace_roots.find_root("ravenna-home")
    if existing:
        stored = workspace_roots._normalize_stored_path(str(existing.get("path") or ""))
        if stored.is_dir():
            return existing

    try:
        return workspace_roots.add_folder_root(str(home), name="Ravenna Home")
    except workspace_roots.WorkspaceRootsError as exc:
        if exc.status_code == 409:
            return workspace_roots.find_root("ravenna-home")
        return None


def ensure_ecosystem_workspace_roots() -> list[str]:
    """Chamado no startup da API — retorna ids de roots garantidos."""
    ensured: list[str] = []
    entry = ensure_ravenna_home_root()
    if entry:
        ensured.append(str(entry.get("id") or "ravenna-home"))
    return ensured


def _list_tree(base: Path, *, limit: int = 24) -> list[str]:
    if not base.is_dir():
        return []
    skip = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}
    found: list[str] = []
    try:
        for path in sorted(base.rglob("*")):
            if any(part in skip for part in path.parts):
                continue
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if rel.endswith((".tsx", ".ts", ".css", ".html", ".json", ".py", ".webmanifest")):
                found.append(rel)
            if len(found) >= limit:
                break
    except OSError:
        return []
    return found


def build_ravenna_home_manifest(project_root: str | None) -> str:
    """Injeta no prompt a árvore real do disco — evita alucinação de arquivos ausentes."""
    scoped = scope_to_project_root(project_root or "ravenna-home/frontend", "")
    home = ravenna_home_dir()
    if not home.is_dir():
        return (
            "MANIFEST RAVENNA HOME:\n"
            f"- Diretório físico ausente: `{home}` — monte `/app/ravenna-home` no container.\n"
            "- Use paths `ravenna-home/frontend/...` em read_file/list_files."
        )
    frontend_dir = home / "frontend" if (home / "frontend").is_dir() else home
    files = _list_tree(frontend_dir)
    pkg = frontend_dir / "package.json"
    lines = [
        "MANIFEST RAVENNA HOME (paths reais no disco — leia antes de concluir que falta arquivo):",
        f"- projectRoot: `{scoped}`",
        f"- Diretório físico: `{frontend_dir}`",
        f"- package.json: {'OK' if pkg.is_file() else 'AUSENTE'}",
        "- Paths canônicos: `ravenna-home/frontend/src/App.tsx`, `ravenna-home/frontend/package.json`.",
        "- Com projectRoot ativo, `read_file('src/App.tsx')` também funciona (escopo automático).",
        "- NÃO use `frontend/...` sozinho sem projectRoot — resolve para `/app/frontend` (inexistente).",
    ]
    if files:
        lines.append("- Arquivos encontrados:")
        for rel in files[:20]:
            lines.append(f"  - `ravenna-home/frontend/{rel}`")
    return "\n".join(lines)


_RAVENNA_HOME_GROUNDING_PATHS = (
    "package.json",
    "src/App.tsx",
    "src/components/Chat.tsx",
    "src/components/InstallPrompt.tsx",
    "src/index.css",
    "src/Layout.tsx",
    "public/manifest.webmanifest",
    "public/icon-192.png",
    "public/icon-512.png",
    "index.html",
    "theme/tokens.css",
)


def build_file_existence_grounding(project_root: str | None) -> str:
    """Prova de existência no disco — fonte de verdade injetada antes do LLM diagnosticar."""
    from learning_agent.core import workspace

    root = (project_root or "ravenna-home/frontend").replace("\\", "/").strip("/")
    lines = [
        "GROUNDING — EXISTÊNCIA NO DISCO (backend leu agora; prevalece sobre suposições do modelo):",
        "REGRA: se EXISTE abaixo, é PROIBIDO afirmar que o arquivo falta. Só diga ausente se marcar AUSENTE.",
        "Use read_file/list_files para editar — não recrie arquivos que já EXISTEM.",
    ]
    for rel in _RAVENNA_HOME_GROUNDING_PATHS:
        canonical = scope_to_project_root(root, rel)
        try:
            data = workspace.read_file(canonical)
            size = data.get("size") or 0
            preview = (data.get("content") or "").splitlines()
            head = preview[0][:100] if preview else ""
            lines.append(f"- EXISTE `{canonical}` ({size} bytes, {len(preview)} linhas) — ex.: {head!r}")
        except workspace.WorkspaceError:
            lines.append(f"- AUSENTE `{canonical}`")

    try:
        listing = workspace.list_directory(scope_to_project_root(root, "src/components"))
        names = [e.get("name") for e in (listing.get("entries") or []) if e.get("type") == "file"]
        if names:
            lines.append(f"- EXISTE `src/components/` — arquivos: {', '.join(names[:12])}")
    except workspace.WorkspaceError:
        lines.append("- AUSENTE `src/components/` (diretório)")

    return "\n".join(lines)


def existing_paths_from_grounding(project_root: str | None, *, extra: list[str] | None = None) -> list[str]:
    """Paths confirmados EXISTE pelo backend (para gate anti-alucinação)."""
    root = (project_root or "ravenna-home/frontend").replace("\\", "/").strip("/")
    found: list[str] = []
    rels = list(_RAVENNA_HOME_GROUNDING_PATHS) + list(extra or [])
    for rel in rels:
        canonical = scope_to_project_root(root, rel) if not rel.startswith("ravenna-home/") else rel
        try:
            from learning_agent.core import workspace

            workspace.read_file(canonical)
            found.append(canonical)
        except Exception:
            continue
    return found


def detect_grounding_hallucinations(text: str, project_root: str | None, *, extra: list[str] | None = None) -> list[str]:
    """Detecta quando o modelo diz 'ausente' para arquivo que GROUNDING provou EXISTE."""
    if not text or not _ABSENT_CLAIM_RE.search(text):
        return []
    existing = existing_paths_from_grounding(project_root, extra=extra)
    if not existing:
        return []
    lower = text.lower()
    violations: list[str] = []
    for path in existing:
        basename = path.rsplit("/", 1)[-1].lower()
        if basename not in lower and path.lower() not in lower:
            continue
        for match in re.finditer(re.escape(basename), lower):
            window = lower[max(0, match.start() - 100) : min(len(lower), match.end() + 100)]
            if _ABSENT_CLAIM_RE.search(window):
                violations.append(
                    f"Alucinação: `{path}` EXISTE no disco (GROUNDING), mas o diagnóstico disse ausente/inexistente."
                )
                break
    return violations


def detect_scope_deviation(text: str, spec: dict[str, Any] | None) -> list[str]:
    """Detecta desvio de escopo (ex.: pytest/backend em épico frontend voice-pwa)."""
    if not text or not spec:
        return []
    mode = spec.get("ravennaHomeUiMode")
    if mode != "voice-pwa":
        return []
    for line in text.splitlines():
        lower = line.lower()
        if not _SCOPE_DEVIATION_RE.search(line):
            continue
        if any(p in lower for p in ("proibido", "proíbido", "nao use", "não use", "ignore", "evite")):
            continue
        return [
            "Desvio de escopo: épico voice-pwa é frontend-only — "
            "PROIBIDO pytest, backend/tests ou backend/main.py no Diagnóstico/Solução."
        ]
    return []


def grounding_violations(
    text: str,
    project_root: str | None,
    spec: dict[str, Any] | None,
    *,
    extra: list[str] | None = None,
) -> list[str]:
    """União de alucinação de existência + desvio de escopo."""
    issues = detect_grounding_hallucinations(text, project_root, extra=extra)
    issues.extend(detect_scope_deviation(text, spec))
    return issues


def required_grounding_reads(spec: dict[str, Any] | None) -> list[str]:
    """Paths que read_file deve cobrir antes de diagnosticar (por modo UI)."""
    if not spec:
        return []
    mode = spec.get("ravennaHomeUiMode")
    if mode == "visual-identity":
        return [
            "theme/tokens.css",
            "theme/visual-identity-index.css",
            "src/index.css",
        ]
    if mode == "gemini-space":
        return [
            "theme/tokens.css",
            "theme/gemini-space-index.css",
            "theme/gemini-space-chat-reference.tsx",
            "src/index.css",
            "src/components/Chat.tsx",
            "src/Layout.tsx",
        ]
    if mode == "web-gemini":
        return [
            "backend/main.py",
            "frontend/src/components/Chat.tsx",
            "frontend/src/api.ts",
        ]
    if mode == "web-gemini-backend":
        return ["main.py", "tests/test_health.py"]
    if mode == "backend-tests-only":
        return ["main.py", "tests/test_health.py", "tests/test_chat_reference.py"]
    if mode == "chat-history-gemini":
        return [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
    if mode == "chat-patch-gemini":
        return [
            "theme/gemini-space-chat-reference.tsx",
            "theme/chat-patch-scaffold.tsx",
            "src/components/Chat.tsx",
        ]
    if mode == "chat-history-autonomy":
        return [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
    if mode == "voice-pwa":
        return list(_VOICE_PWA_REQUIRED_READS)
    if spec.get("requireGroundingTools"):
        return ["package.json", "src/components/Chat.tsx", "src/App.tsx", "index.html"]
    return []


def build_grounding_repair_prompt(
    violations: list[str],
    original_request: str,
    project_root: str | None,
    *,
    extra: list[str] | None = None,
) -> str:
    grounding = build_file_existence_grounding(project_root)
    issues = "\n".join(f"- {v}" for v in violations)
    return (
        f"{original_request}\n\n"
        "---\n"
        "REPAIR GROUNDING (obrigatório — sua Investigação/Diagnóstico anterior foi REJEITADA):\n"
        f"{issues}\n\n"
        "Corrija: use SOMENTE evidência de read_file/list_files ou GROUNDING abaixo.\n"
        "NÃO afirme ausência de arquivo marcado EXISTE. Foque em ```write```/```patch``` na entrega.\n\n"
        f"{grounding}"
    )


def preflight_read_file_messages(
    project_root: str | None,
    *,
    paths: list[str] | None = None,
    max_files: int = 6,
) -> list[dict[str, str]]:
    """Mensagens sintéticas simulando read_file já executado (obrigatório antes de diagnosticar)."""
    from learning_agent.core import agent_tools

    root = project_root or "ravenna-home/frontend"
    token = agent_tools.set_tool_project_root(root)
    messages: list[dict[str, str]] = []
    try:
        rels = paths or ["package.json", "src/components/Chat.tsx", "src/App.tsx", "index.html"]
        canonical = [
            scope_to_project_root(root, rel) if not rel.startswith("ravenna-home/") else rel
            for rel in rels
        ][:max_files]
        paths = canonical
        summary_lines = ["PRÉ-LEITURA OBRIGATÓRIA (backend executou read_file — use como evidência):"]
        for path in paths:
            result = agent_tools.execute_tool("read_file", {"path": path, "max_lines": 24})
            summary_lines.append(f"### read_file `{path}`\n{result[:2000]}")
        messages.append(
            {
                "role": "user",
                "content": "\n\n".join(summary_lines)
                + "\n\nAgora investigue com base NESTA evidência. Proibido dizer ausente o que read_file provou exists:true.",
            }
        )
    finally:
        agent_tools.reset_tool_project_root(token)
    return messages
