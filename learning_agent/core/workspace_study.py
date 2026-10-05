"""Estudo inteligente de workspace — coleta em camadas, análise profunda, digest e verificação."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from learning_agent.core.workspace import WorkspaceError, read_file
from learning_agent.core.workspace_roots import find_root, list_roots

TIER_MANIFEST: list[tuple[str, list[str]]] = [
    (
        "entry",
        [
            "run.py",
            "app.py",
            "main.py",
            "wsgi.py",
            "docker-compose.yml",
            "docker-compose.local.yml",
            "Dockerfile",
            "requirements.txt",
            "requirements-dev.txt",
            "pyproject.toml",
            "package.json",
            "README.md",
        ],
    ),
    (
        "core",
        [
            "remote_app/__init__.py",
            "remote_app/config.py",
            "remote_app/models.py",
            "remote_app/routes.py",
            "remote_app/hub.py",
            "remote_app/navigation.py",
            "remote_app/copilot.py",
            "remote_app/noc_pulse.py",
            "remote_app/scheduler.py",
            "remote_app/sockets.py",
            "remote_app/prtg_client.py",
            "remote_app/infraco.py",
            "remote_app/material_routes.py",
            "src/main.ts",
            "src/App.tsx",
        ],
    ),
    (
        "ui",
        [
            "remote_app/templates/base.html",
            "remote_app/templates/hub.html",
            "remote_app/templates/copilot.html",
            "remote_app/templates/_sidebar_nav.html",
        ],
    ),
    (
        "docs",
        [
            "docs/ROADMAP_COPILOT.md",
            "docs/DADOS-PROTECAO.md",
            "docs/GIT-SYNC-AUTO.md",
        ],
    ),
]

ROUTE_RE = re.compile(
    r"@\s*(?:[\w.]+\.)?route\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
MODEL_CLASS_RE = re.compile(r"^class\s+(\w+)\s*\(", re.MULTILINE)
DOCKER_SERVICE_RE = re.compile(r"^\s{2}(\w[\w-]*):\s*$", re.MULTILINE)
MENU_TITLE_RE = re.compile(r'"title":\s*"([^"]+)"')
PIPELINE_STATUS_RE = re.compile(r"'([^']+)',\s*$", re.MULTILINE)
REQUIREMENTS_PKG_RE = re.compile(r"^([A-Za-z0-9_-]+)", re.MULTILINE)
SOCKET_EVENT_RE = re.compile(r"@socketio\.on\s*\(\s*['\"]([^'\"]+)['\"]")
API_AI_ROUTE_RE = re.compile(r"/api/ai/\w+")


def _root_disk_path(root_id: str) -> Path:
    from learning_agent.core.workspace_roots import get_root_path

    return get_root_path(root_id)


def _canonical(root_id: str, inner: str) -> str:
    inner = inner.replace("\\", "/").strip("/")
    return f"{root_id}/{inner}" if inner else root_id


def _resolve_manifest_paths(root_id: str) -> list[str]:
    root = _root_disk_path(root_id)
    found: list[str] = []
    seen: set[str] = set()
    for _tier, names in TIER_MANIFEST:
        for name in names:
            candidate = root / Path(name)
            if not candidate.is_file():
                continue
            inner = candidate.relative_to(root).as_posix()
            canon = _canonical(root_id, inner)
            if canon not in seen:
                seen.add(canon)
                found.append(canon)
    return found


def _walk_extra_py(root_id: str, *, max_files: int = 10) -> list[str]:
    root = _root_disk_path(root_id)
    extras: list[str] = []
    for folder in ("remote_app", "src", "app", "backend"):
        base = root / folder
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if len(extras) >= max_files:
                break
            if child.suffix == ".py" and child.is_file():
                extras.append(_canonical(root_id, child.relative_to(root).as_posix()))
    return extras


def _list_templates(root_id: str, *, max_names: int = 40) -> list[str]:
    root = _root_disk_path(root_id)
    tpl_dir = root / "remote_app" / "templates"
    if not tpl_dir.is_dir():
        return []
    names: list[str] = []
    for child in sorted(tpl_dir.rglob("*.html")):
        names.append(child.relative_to(tpl_dir).as_posix())
        if len(names) >= max_names:
            break
    return names


def collect_study_paths(root_ids: list[str], *, max_files: int = 36) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for root_id in root_ids:
        if not find_root(root_id):
            continue
        for path in _resolve_manifest_paths(root_id):
            if path not in seen:
                seen.add(path)
                out.append(path)
        for path in _walk_extra_py(root_id):
            if path not in seen and len(out) < max_files:
                seen.add(path)
                out.append(path)
        if len(out) >= max_files:
            break
    return out[:max_files]


def _read_paths(paths: list[str]) -> tuple[dict[str, str], list[str], list[dict[str, Any]]]:
    cache: dict[str, str] = {}
    errors: list[str] = []
    files_read: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = read_file(path)
            content = str(data.get("content") or "")
            cache[path] = content
            files_read.append(
                {
                    "path": path,
                    "size": int(data.get("size") or 0),
                    "lines": content.count("\n") + 1,
                }
            )
        except WorkspaceError as exc:
            errors.append(f"{path}: {exc.message}")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
    return cache, errors, files_read


def _group_routes(routes: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "api_ai": [],
        "api_other": [],
        "api_noc": [],
        "views": [],
        "pages": [],
        "static": [],
        "other": [],
    }
    for route in routes:
        if route.startswith("/api/ai"):
            groups["api_ai"].append(route)
        elif route.startswith("/api/noc") or route.startswith("/api/notifications"):
            groups["api_noc"].append(route)
        elif route.startswith("/api/"):
            groups["api_other"].append(route)
        elif route.startswith("/view/"):
            groups["views"].append(route)
        elif route.startswith("/"):
            groups["pages"].append(route)
        else:
            groups["other"].append(route)
    return {k: v for k, v in groups.items() if v}


def build_deep_analysis(root_id: str, cache: dict[str, str]) -> dict[str, Any]:
    """Segunda passa — mapa estrutural sem depender do LLM."""
    deep: dict[str, Any] = {"root_id": root_id}

    routes_content = ""
    for path, content in cache.items():
        if path.endswith("/routes.py"):
            routes_content = content
            break

    if routes_content:
        routes = ROUTE_RE.findall(routes_content)
        deep["route_total"] = len(routes)
        deep["routes_by_group"] = _group_routes(routes)
        deep["routes_sample"] = routes[:25]

    for path, content in cache.items():
        name = path.split("/")[-1]
        if name == "models.py":
            deep["model_classes"] = MODEL_CLASS_RE.findall(content)
        elif name == "hub.py":
            deep["hub_modules"] = re.findall(r"'id':\s*'(\w+)'", content)
        elif name == "navigation.py":
            deep["menu_titles"] = MENU_TITLE_RE.findall(content)[:30]
        elif name == "requirements.txt":
            pkgs = [
                m.group(1).lower()
                for m in REQUIREMENTS_PKG_RE.finditer(content)
                if m.group(1) and not m.group(1).startswith("#")
            ]
            deep["dependencies"] = pkgs[:25]
        elif name == "sockets.py":
            deep["socket_events"] = SOCKET_EVENT_RE.findall(content)
        elif "docker-compose" in name and name.endswith((".yml", ".yaml")):
            deep.setdefault("docker_services", [])
            deep["docker_services"] = DOCKER_SERVICE_RE.findall(content)
        elif name in ("noc_pulse.py", "copilot.py"):
            statuses = [
                s for s in PIPELINE_STATUS_RE.findall(content)
                if len(s) > 3 and s[0].isupper()
            ]
            if statuses:
                deep.setdefault("pipeline_statuses", [])
                deep["pipeline_statuses"].extend(statuses)

    if deep.get("pipeline_statuses"):
        seen: set[str] = set()
        ordered: list[str] = []
        for s in deep["pipeline_statuses"]:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        deep["pipeline_statuses"] = ordered[:20]

    deep["templates"] = _list_templates(root_id)
    deep["template_count"] = len(deep["templates"])
    deep["py_modules"] = sorted(
        {p.split("/")[-1] for p in cache if p.endswith(".py") and "/remote_app/" in p}
    )

    stack: list[str] = []
    deps = [d.lower() for d in deep.get("dependencies") or []]
    if any(d.startswith("flask") for d in deps):
        stack.append("Flask")
    if any("sqlalchemy" in d or d == "flask-sqlalchemy" for d in deps):
        stack.append("SQLAlchemy")
    if any("socketio" in d for d in deps):
        stack.append("Flask-SocketIO")
    if any("gunicorn" in d for d in deps):
        stack.append("Gunicorn")
    if any("postgres" in d or "psycopg" in d for d in deps):
        stack.append("PostgreSQL")
    if "docker_services" in deep:
        stack.append("Docker Compose")
    deep["stack_hints"] = stack

    return deep


def _format_study_map(deep: dict[str, Any], *, prior_hint: str | None = None) -> str:
    lines = [
        "## STUDY MAP (análise automática — leia primeiro)",
        f"- Root: `{deep.get('root_id', '?')}`",
    ]
    if prior_hint:
        lines.append(f"- Estudo anterior (RAG): {prior_hint[:400]}")
    if deep.get("stack_hints"):
        lines.append(f"- Stack detectada: {', '.join(deep['stack_hints'])}")
    if deep.get("docker_services"):
        lines.append(f"- Serviços Docker: {', '.join(deep['docker_services'])}")
    if deep.get("hub_modules"):
        lines.append(f"- Módulos Hub: {', '.join(deep['hub_modules'])}")
    if deep.get("menu_titles"):
        lines.append(f"- Menu lateral: {', '.join(deep['menu_titles'][:12])}")
    if deep.get("model_classes"):
        lines.append(f"- Entidades ORM ({len(deep['model_classes'])}): {', '.join(deep['model_classes'])}")
    if deep.get("pipeline_statuses"):
        lines.append(f"- Status pipeline: {' → '.join(deep['pipeline_statuses'][:10])}")
    if deep.get("route_total"):
        lines.append(f"- Rotas HTTP: {deep['route_total']} total")
        for group, items in (deep.get("routes_by_group") or {}).items():
            lines.append(f"  - {group}: {len(items)} — ex.: {', '.join(items[:6])}")
    if deep.get("socket_events"):
        lines.append(f"- Eventos SocketIO: {', '.join(deep['socket_events'])}")
    if deep.get("template_count"):
        lines.append(
            f"- Templates HTML: {deep['template_count']} — "
            f"{', '.join(deep.get('templates', [])[:8])}"
        )
    if deep.get("py_modules"):
        lines.append(f"- Módulos Python remote_app/: {len(deep['py_modules'])}")
    lines.append("")
    return "\n".join(lines)


def _excerpt(content: str, *, head: int = 120, tail: int = 0, max_chars: int = 9000) -> str:
    lines = content.splitlines()
    if len(lines) <= head + tail:
        text = content
    else:
        parts = lines[:head]
        if tail:
            parts.append("... [trecho omitido] ...")
            parts.extend(lines[-tail:])
        text = "\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncado]"
    return text


def _recall_prior_study(root_id: str) -> str | None:
    try:
        from learning_agent.core import knowledge

        hits = knowledge.search(f"Estudo workspace {root_id} REMOTE_APP aplicação", limit=2)
        if not hits:
            return None
        snippets = []
        for hit in hits:
            title = str(hit.get("metadata", {}).get("title") or hit.get("document", "")[:80])
            body = str(hit.get("document") or "")[:350]
            snippets.append(f"{title}: {body}")
        return " | ".join(snippets)
    except Exception:
        return None


def build_study_digest(
    root_ids: list[str],
    *,
    max_files: int = 36,
    recall_prior: bool = True,
) -> dict[str, Any]:
    paths = collect_study_paths(root_ids, max_files=max_files)
    cache, errors, files_read = _read_paths(paths)

    deep_by_root: list[dict[str, Any]] = []
    prior_hints: list[str] = []
    for root_id in root_ids:
        if not find_root(root_id):
            continue
        deep = build_deep_analysis(root_id, cache)
        deep_by_root.append(deep)
        if recall_prior:
            hint = _recall_prior_study(root_id)
            if hint:
                prior_hints.append(hint)

    digest_parts = [
        "# RAVENNA WORKSPACE STUDY DIGEST",
        f"Roots: {', '.join(root_ids)}",
        f"Arquivos lidos: {len(files_read)}",
        "",
    ]
    prior_line = prior_hints[0] if prior_hints else None
    for deep in deep_by_root:
        digest_parts.append(_format_study_map(deep, prior_hint=prior_line))
        prior_line = None

    for path in paths:
        content = cache.get(path)
        if not content:
            continue
        size = len(content.encode("utf-8"))
        if path.endswith("routes.py") or path.endswith("copilot.py"):
            excerpt = _excerpt(content, head=80, max_chars=5000)
            digest_parts.extend([f"## @file {path} (trecho — mapa de rotas acima)", "```", excerpt, "```", ""])
        elif size > 12_000:
            excerpt = _excerpt(content, head=70, tail=15, max_chars=5000)
            digest_parts.extend([f"## @file {path}", "```", excerpt, "```", ""])
        elif path.endswith(".html"):
            excerpt = _excerpt(content, head=40, max_chars=2500)
            digest_parts.extend([f"## @file {path} (template)", "```", excerpt, "```", ""])
        else:
            excerpt = _excerpt(content, head=100, max_chars=7000)
            digest_parts.extend([f"## @file {path}", "```", excerpt, "```", ""])

    digest = "\n".join(digest_parts)
    if len(digest) > 52_000:
        digest = digest[:52_000] + "\n... [digest truncado para contexto LLM]"

    analysis = deep_by_root
    return {
        "root_ids": root_ids,
        "files": [f["path"] for f in files_read],
        "files_read": files_read,
        "analysis": analysis,
        "deep_analysis": deep_by_root,
        "prior_study": prior_hints,
        "errors": errors,
        "digest": digest,
        "digest_chars": len(digest),
    }


STUDY_SYSTEM = """MODO ESTUDO DE APLICAÇÃO (obrigatório):
- Você recebeu um WORKSPACE STUDY DIGEST com leitura real de arquivos do projeto.
- Leia PRIMEIRO a seção **STUDY MAP** — ela condensa rotas, entidades, stack e módulos.
- PROIBIDO dizer "vou estudar e volto" — entregue a análise AGORA com base no digest.
- Estruture a resposta:
  1) O que é a aplicação (1 parágrafo)
  2) Stack técnica (framework, DB, deploy, integrações)
  3) Módulos/funcionalidades principais (tabela ou lista)
  4) Modelo de dados / entidades centrais
  5) Rotas/APIs mais importantes (use o STUDY MAP)
  6) Fluxo operacional ponta a ponta (status pipeline → OS → conclusão)
  7) Frontend/templates (se houver)
  8) Pontos de extensão ou riscos técnicos
- Cite paths reais dos arquivos lidos (ex.: remote_app/models.py).
- Não invente módulos que não aparecem no digest ou STUDY MAP.
- Ignore integração SSH/Ravenna — foque só na aplicação anexada."""


def verify_study_reply(reply: str, deep_list: list[dict[str, Any]]) -> dict[str, Any]:
    """Verificação heurística — a resposta cobre fatos extraídos do código?"""
    text = reply.lower()
    checks: list[dict[str, Any]] = []

    def check(label: str, terms: list[str], *, min_hits: int = 1) -> None:
        hits = [t for t in terms if t.lower() in text]
        checks.append(
            {
                "label": label,
                "expected": terms,
                "hits": hits,
                "ok": len(hits) >= min_hits,
            }
        )

    merged: dict[str, Any] = {}
    for deep in deep_list:
        for k, v in deep.items():
            if k not in merged:
                merged[k] = v
            elif isinstance(v, list) and isinstance(merged.get(k), list):
                merged[k] = list(dict.fromkeys([*merged[k], *v]))

    if merged.get("stack_hints"):
        check("stack", merged["stack_hints"], min_hits=1)
    if merged.get("model_classes"):
        key_models = [c for c in merged["model_classes"] if c in ("Atividade", "User", "FlowControl")]
        if not key_models:
            key_models = merged["model_classes"][:3]
        check("entidades ORM", key_models, min_hits=1)
    if merged.get("hub_modules"):
        check("módulos hub", merged["hub_modules"][:5], min_hits=2)
    if merged.get("route_total"):
        check("rotas/API", ["rota", "api", "/acionamentos", "/copilot", "endpoint"], min_hits=2)
    if merged.get("pipeline_statuses"):
        check("pipeline operacional", merged["pipeline_statuses"][:4], min_hits=1)
    check("profundidade", ["flask", "postgres", "docker", "gunicorn", "socket"], min_hits=1)

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks) or 1
    return {
        "score": round(100 * passed / total),
        "passed": passed,
        "total": total,
        "checks": checks,
        "ok": passed >= max(1, total - 1),
    }


def synthesize_study_reply(
    user_message: str,
    digest: str,
    *,
    root_ids: list[str] | None = None,
) -> dict[str, Any]:
    from learning_agent.core.chat import _call_llm

    roots_line = f"Roots estudados: {', '.join(root_ids or [])}\n\n"
    prompt = (
        f"{user_message.strip()}\n\n"
        "--- WORKSPACE STUDY DIGEST (leitura real do servidor) ---\n"
        f"{roots_line}{digest}"
    )
    messages = [
        {"role": "system", "content": STUDY_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    answer, model = _call_llm(messages, task_mode="agent", max_tokens=4096)
    return {"reply": answer.strip(), "model": model}


def run_workspace_study(
    root_ids: list[str],
    *,
    user_message: str = "Estude a aplicação anexada de ponta a ponta.",
    synthesize: bool = True,
    persist_note: bool = True,
    verify: bool = True,
    recall_prior: bool = True,
    max_files: int = 36,
) -> dict[str, Any]:
    if not root_ids:
        valid = [r["id"] for r in list_roots()]
        root_ids = valid[:1]

    pack = build_study_digest(root_ids, max_files=max_files, recall_prior=recall_prior)
    result: dict[str, Any] = {
        "success": True,
        "root_ids": root_ids,
        "files": pack["files"],
        "files_read": pack["files_read"],
        "analysis": pack["analysis"],
        "deep_analysis": pack["deep_analysis"],
        "prior_study": pack.get("prior_study") or [],
        "errors": pack["errors"],
        "digest_chars": pack["digest_chars"],
        "digest": pack["digest"],
    }

    if synthesize:
        synth = synthesize_study_reply(user_message, pack["digest"], root_ids=root_ids)
        result["reply"] = synth["reply"]
        result["model"] = synth["model"]
        if verify and result.get("reply"):
            result["verification"] = verify_study_reply(
                result["reply"], pack.get("deep_analysis") or []
            )

    if persist_note and pack["files"]:
        try:
            from learning_agent.core import knowledge

            root = root_ids[0] if root_ids else "unknown"
            title = f"[Estudo workspace] {root}"
            summary = result.get("reply") or pack["digest"][:2500]
            deep_json = json.dumps(pack.get("deep_analysis") or [], ensure_ascii=False)[:1500]
            body = f"{summary}\n\n--- deep_analysis ---\n{deep_json}"
            knowledge.add_note(
                title,
                body[:4000],
                tags=["workspace-study", f"root:{root}", "remote_app-study"],
                sync_cloud=False,
            )
            result["note_saved"] = True
        except Exception as exc:
            result["note_saved"] = False
            result["note_error"] = str(exc)[:200]

    return result
