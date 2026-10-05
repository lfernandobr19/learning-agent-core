"""Criação e gestão de agentes — Ravenna como especialista em agentes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from learning_agent import db
from learning_agent.config import PROJECT_ROOT

AGENTS_DIR = PROJECT_ROOT / ".cursor" / "agents"
SKILLS_DIR = PROJECT_ROOT / ".cursor" / "skills"
REGISTRY_PATH = PROJECT_ROOT / "agents" / "registry.yaml"
ARCHETYPES_DIR = PROJECT_ROOT / "agents" / "archetypes"
PROJECTS_DIR = PROJECT_ROOT / "agents" / "projects"

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

LEARNING_LOOP = """## Aprendizado contínuo (obrigatório)

Este agente **evolui a cada sessão**. O conhecimento fica em tags `{tags}`.

### Início de cada sessão
1. `search_knowledge` — consulte o que já aprendeu neste domínio
2. `get_context_for_task` — monte contexto antes de implementar ou vistoriar
3. `get_related_errors` — evite repetir falhas conhecidas

### Durante o trabalho
4. `search_code` — padrões e convenções do repositório
5. `search_and_learn` — quando encontrar lacuna técnica nova na internet
6. Documente decisões não óbvias inline no código quando necessário

### Ao concluir cada entrega
7. `add_learning_note` com título prefixo **{note_prefix}**
8. `create_quiz` — 1 a 3 perguntas para consolidar conceitos novos
9. `record_session` — resumo da sessão com tópicos e decisões

### Quando falhar
10. `record_failure` — contexto, erro e correção
11. Corrija e valide com provas reais antes de considerar pronto

### Aprendizado entre agentes (obrigatório)
12. `get_peer_insights` — absorva o que outros agentes aprenderam
13. `agent_share_insight` — compartilhe descobertas com os peers
14. `detect_agent_gaps` — identifique o que ainda não domina
15. `agent_research_gaps` — pesquise e indexe lacunas automaticamente
16. Participe de `run_agent_roundtable` quando a Ravenna convocar
"""

SKILL_BODY = """# {display_name} — Aprendizado

Skill de aprendizado contínuo do agente **{display_name}** (`{slug}`).

## Quando usar

- Ao iniciar sessão delegada a `{slug}`
- Ao encerrar entrega do agente `{slug}`
- Quando `{slug}` encontrar lacuna de conhecimento

## Loop

{learning_excerpt}

## Tags de conhecimento

`{tags}`
"""


def _slug(name: str) -> str:
    slug = name.strip().lower().replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str | None]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, "frontmatter ausente (esperado --- no início)"
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return {}, f"frontmatter inválido: {exc}"
    if not isinstance(meta, dict):
        return {}, "frontmatter deve ser um objeto YAML"
    return meta, None


def _load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.is_file():
        return {"version": 1, "user_agents": [], "supervisors": []}
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _save_registry(data: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_PATH.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _register_in_registry(
    *,
    name: str,
    archetype: str,
    file_path: str,
    focus: str,
    project_dir: str,
) -> None:
    data = _load_registry()
    agents = data.setdefault("user_agents", [])
    entry = {
        "name": name,
        "kind": "agent_project",
        "archetype": archetype,
        "file": file_path,
        "project": project_dir,
        "parent": "ravenna",
        "focus": focus,
        "learning": True,
    }
    agents = [a for a in agents if a.get("name") != name]
    agents.append(entry)
    data["user_agents"] = agents
    if "archetypes" not in data:
        data["archetypes"] = list_archetypes()["archetypes"]
    _save_registry(data)


def _register_agent(
    *,
    name: str,
    kind: str,
    file_path: Path,
    description: str,
    role: str = "",
    tags: list[str] | None = None,
    parent_agent: str = "ravenna",
) -> dict[str, Any]:
    db.init_db()
    now = db._utcnow()
    rel = str(file_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    tag_json = json.dumps(tags or [], ensure_ascii=False)
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO agent_definitions
                (name, kind, role, description, file_path, tags, parent_agent, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                kind = excluded.kind,
                role = excluded.role,
                description = excluded.description,
                file_path = excluded.file_path,
                tags = excluded.tags,
                parent_agent = excluded.parent_agent,
                updated_at = excluded.updated_at
            """,
            (name, kind, role, description, rel, tag_json, parent_agent, now, now),
        )
    return {"name": name, "kind": kind, "file_path": rel, "registered": True}


def load_archetype(archetype_id: str) -> dict[str, Any]:
    aid = _slug(archetype_id)
    path = ARCHETYPES_DIR / f"{aid}.yaml"
    if not path.is_file():
        return {"success": False, "error": f"arquétipo não encontrado: {archetype_id}"}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {"success": False, "error": f"arquétipo inválido: {archetype_id}"}
    data["success"] = True
    data["id"] = data.get("id", aid)
    return data


def list_archetypes() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if ARCHETYPES_DIR.is_dir():
        for path in sorted(ARCHETYPES_DIR.glob("*.yaml")):
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if isinstance(data, dict):
                items.append(
                    {
                        "id": data.get("id", path.stem),
                        "label": data.get("label", path.stem),
                        "summary": data.get("summary", ""),
                        "focus": data.get("focus", ""),
                        "learning_tags": data.get("learning_tags", []),
                    }
                )
    return {
        "success": True,
        "archetypes": items,
        "hint": "Use scaffold_agent_project(name, archetype, ...) para criar agente completo",
    }


def _bullet_section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    lines = "\n".join(f"- {item}" for item in items)
    return f"## {title}\n\n{lines}\n"


def _tools_section(required: list[str], recommended: list[str]) -> str:
    req = ", ".join(f"`{t}`" for t in required) or "—"
    rec = ", ".join(f"`{t}`" for t in recommended) or "—"
    return f"""## Tools MCP

**Obrigatórias:** {req}

**Recomendadas:** {rec}
"""


def _build_agent_body(
    archetype: dict[str, Any],
    *,
    display_name: str,
    slug: str,
    focus: str,
    triggers: str,
) -> str:
    tags = ", ".join(archetype.get("learning_tags", []))
    note_prefix = f"Agente {slug}"
    learning = LEARNING_LOOP.format(tags=tags, note_prefix=note_prefix)

    parts = [
        f"Você é o agente **{display_name}** da **Ravenna** — subagente dela, "
        f"especialista em {focus or archetype.get('focus', 'seu domínio')}.",
        f"Arquétipo: **{archetype.get('label', 'Custom')}**.",
        "",
        "## Quando ser invocado",
        "",
        triggers.strip(),
        "",
        _bullet_section("Domínios", archetype.get("domains", [])),
        _bullet_section("Fluxo de trabalho", archetype.get("workflow", [])),
        _bullet_section("Provas e qualidade", archetype.get("proofs", [])),
        _tools_section(
            archetype.get("mcp_tools", {}).get("required", []),
            archetype.get("mcp_tools", {}).get("recommended", []),
        ),
        learning,
        "## Integração IDE",
        "",
        "- Mensagens no Observador: `post_theater_message` quando relevante",
        "- Ravenna orquestra; reporte bloqueios e decisões importantes a ela",
        "- Ao falar da Ravenna, use feminino (\"ela\", \"a engenheira\")",
    ]
    return "\n".join(parts).strip() + "\n"


def _build_playbook(
    archetype: dict[str, Any],
    *,
    display_name: str,
    slug: str,
    focus: str,
) -> str:
    tags = ", ".join(archetype.get("learning_tags", []))
    return f"""# Playbook — {display_name}

Agente: `{slug}` | Arquétipo: `{archetype.get('id', 'custom')}`

## Missão

{focus or archetype.get('focus', '')}

## Escopo

{archetype.get('summary', '')}

{_bullet_section('Domínios cobertos', archetype.get('domains', []))}
{_bullet_section('Fluxo padrão', archetype.get('workflow', []))}
{_bullet_section('Critérios de qualidade', archetype.get('proofs', []))}

## Evolução do playbook

Quando este agente descobrir padrões novos, a Ravenna ou o próprio agente deve:

1. Atualizar este playbook com a seção nova
2. Registrar em `add_learning_note` com tag `{tags}`
3. Opcionalmente criar quiz para consolidar

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `manifest.yaml` | Metadados, arquétipo e config de aprendizado |
| `playbook.md` | Este arquivo — fluxos e domínio |
| `.cursor/agents/{slug}.md` | Definição delegável no Cursor |
| `.cursor/skills/{slug}-learning/SKILL.md` | Loop de aprendizado |
"""


def _build_manifest(
    archetype: dict[str, Any],
    *,
    slug: str,
    display_name: str,
    description: str,
    focus: str,
) -> dict[str, Any]:
    tools = archetype.get("mcp_tools", {})
    return {
        "version": 1,
        "name": slug,
        "display_name": display_name,
        "archetype": archetype.get("id", "custom"),
        "description": description,
        "focus": focus or archetype.get("focus", ""),
        "created_by": "ravenna",
        "learning": {
            "enabled": True,
            "tags": archetype.get("learning_tags", []),
            "note_prefix": f"Agente {slug}",
            "on_start": [
                "search_knowledge",
                "get_context_for_task",
                "get_related_errors",
                "get_peer_insights",
            ],
            "on_complete": ["add_learning_note", "create_quiz", "record_session", "agent_share_insight"],
            "on_unknown": ["detect_agent_gaps", "agent_research_gaps", "search_and_learn", "search_code"],
            "on_failure": ["record_failure"],
            "peer_learning": {
                "enabled": True,
                "share_with": "all_agents",
                "absorb_from": "all_agents",
                "roundtable": True,
            },
        },
        "mcp_tools": tools,
        "files": {
            "agent": f".cursor/agents/{slug}.md",
            "playbook": f"agents/projects/{slug}/playbook.md",
            "learning_skill": f".cursor/skills/{slug}-learning/SKILL.md",
        },
    }


def scaffold_agent_project(
    name: str,
    archetype: str,
    description: str = "",
    *,
    focus: str = "",
    triggers: str = "",
    display_name: str = "",
    parent_agent: str = "ravenna",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Cria projeto completo de agente: manifest, playbook, subagente Cursor e skill de aprendizado."""
    slug = _slug(name)
    if not _NAME_RE.match(slug):
        return {
            "success": False,
            "error": "name deve ser kebab-case (a-z, 0-9, hífen), 2–49 caracteres",
        }

    arch = load_archetype(archetype)
    if not arch.get("success"):
        available = [a["id"] for a in list_archetypes()["archetypes"]]
        return {
            "success": False,
            "error": arch.get("error", "arquétipo inválido"),
            "available_archetypes": available,
        }

    project_dir = PROJECTS_DIR / slug
    agent_path = AGENTS_DIR / f"{slug}.md"
    skill_dir = SKILLS_DIR / f"{slug}-learning"
    skill_path = skill_dir / "SKILL.md"
    manifest_path = project_dir / "manifest.yaml"
    playbook_path = project_dir / "playbook.md"

    exists = agent_path.exists() or manifest_path.exists()
    if exists and not overwrite:
        return {
            "success": False,
            "error": f"projeto de agente já existe: {slug}",
            "hint": "use overwrite=true para substituir",
        }

    label = display_name.strip() or slug.replace("-", " ").title()
    desc = description.strip() or (
        f"{arch.get('label', 'Agente')} — {arch.get('summary', focus or 'especialista')}"
    )
    trig = triggers.strip() or arch.get("default_triggers", "Quando o usuário pedir este domínio.")
    agent_focus = focus.strip() or arch.get("focus", "")

    project_dir.mkdir(parents=True, exist_ok=True)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)

    body = _build_agent_body(
        arch, display_name=label, slug=slug, focus=agent_focus, triggers=trig
    )
    agent_content = f"---\nname: {slug}\ndescription: >-\n  {desc.replace(chr(10), ' ')}\n---\n\n{body}"
    agent_path.write_text(agent_content, encoding="utf-8")

    playbook_path.write_text(
        _build_playbook(arch, display_name=label, slug=slug, focus=agent_focus),
        encoding="utf-8",
    )

    manifest = _build_manifest(
        arch, slug=slug, display_name=label, description=desc, focus=agent_focus
    )
    with manifest_path.open("w", encoding="utf-8") as fh:
        yaml.dump(manifest, fh, allow_unicode=True, sort_keys=False, default_flow_style=False)

    tags = ", ".join(arch.get("learning_tags", []))
    note_prefix = f"Agente {slug}"
    learning_excerpt = (
        f"Início: search_knowledge + get_context_for_task. "
        f"Fim: add_learning_note ({note_prefix}) + create_quiz + record_session."
    )
    skill_content = (
        f"---\nname: {slug}-learning\ndescription: >-\n  "
        f"Loop de aprendizado do agente {slug} ({arch.get('label', '')}). "
        f"Acione ao delegar ou encerrar sessão deste agente.\n---\n\n"
        + SKILL_BODY.format(
            display_name=label,
            slug=slug,
            learning_excerpt=learning_excerpt,
            tags=tags,
        )
    )
    skill_path.write_text(skill_content, encoding="utf-8")

    tags_list = list(arch.get("learning_tags", [])) + ["agent-project", archetype]
    registration = _register_agent(
        name=slug,
        kind="agent_project",
        file_path=agent_path,
        description=desc,
        role=agent_focus,
        parent_agent=parent_agent,
        tags=tags_list,
    )

    rel_project = str(project_dir.relative_to(PROJECT_ROOT)).replace("\\", "/")
    _register_in_registry(
        name=slug,
        archetype=arch.get("id", archetype),
        file_path=registration["file_path"],
        focus=agent_focus,
        project_dir=rel_project,
    )

    validation = validate_agent_definition(registration["file_path"])

    return {
        "success": True,
        "created": True,
        "name": slug,
        "archetype": arch.get("id"),
        "archetype_label": arch.get("label"),
        "display_name": label,
        "learning_enabled": True,
        "files": {
            "agent": registration["file_path"],
            "manifest": f"{rel_project}/manifest.yaml",
            "playbook": f"{rel_project}/playbook.md",
            "learning_skill": str(skill_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        },
        "validation": validation,
        "next_steps": [
            f"Delegue no Cursor: subagente `{slug}`",
            f"Leia o playbook: `agents/projects/{slug}/playbook.md`",
            "O agente aprende automaticamente via loop MCP em cada sessão",
            f"Para outro domínio: `scaffold_agent_project(nome, archetype)` com backend | frontend | qa-inspector | data | custom",
        ],
    }


def list_agents() -> dict[str, Any]:
    registry = _load_registry()
    db.init_db()

    db_rows: dict[str, dict[str, Any]] = {}
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT name, kind, role, description, file_path, tags, parent_agent, created_at FROM agent_definitions"
        ).fetchall()
    for row in rows:
        db_rows[row["name"]] = {
            "name": row["name"],
            "kind": row["kind"],
            "role": row["role"],
            "description": row["description"],
            "file_path": row["file_path"],
            "tags": json.loads(row["tags"] or "[]"),
            "parent_agent": row["parent_agent"],
            "created_at": row["created_at"],
            "source": "database",
        }

    projects: list[dict[str, Any]] = []
    if PROJECTS_DIR.is_dir():
        for manifest_file in sorted(PROJECTS_DIR.glob("*/manifest.yaml")):
            with manifest_file.open(encoding="utf-8") as fh:
                manifest = yaml.safe_load(fh) or {}
            if isinstance(manifest, dict):
                learning = manifest.get("learning")
                if isinstance(learning, dict):
                    learning_enabled = learning.get("enabled", False)
                elif isinstance(learning, bool):
                    learning_enabled = learning
                else:
                    learning_enabled = False
                projects.append(
                    {
                        "name": manifest.get("name", manifest_file.parent.name),
                        "kind": "agent_project",
                        "archetype": manifest.get("archetype"),
                        "display_name": manifest.get("display_name"),
                        "focus": manifest.get("focus"),
                        "learning_enabled": learning_enabled,
                        "project_path": str(manifest_file.parent.relative_to(PROJECT_ROOT)).replace(
                            "\\", "/"
                        ),
                        "source": "project",
                    }
                )

    filesystem: list[dict[str, Any]] = []
    if AGENTS_DIR.is_dir():
        for path in sorted(AGENTS_DIR.glob("*.md")):
            name = path.stem
            meta, err = _parse_frontmatter(path.read_text(encoding="utf-8"))
            filesystem.append(
                {
                    "name": name,
                    "kind": "cursor_subagent",
                    "file_path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "description": str(meta.get("description", "")),
                    "valid": err is None and bool(meta.get("name")) and bool(meta.get("description")),
                    "validation_error": err,
                    "source": "filesystem",
                }
            )

    skills: list[dict[str, Any]] = []
    if SKILLS_DIR.is_dir():
        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            meta, err = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            skills.append(
                {
                    "name": skill_dir.name,
                    "kind": "cursor_skill",
                    "file_path": str(skill_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                    "description": str(meta.get("description", "")),
                    "valid": err is None and bool(meta.get("name")) and bool(meta.get("description")),
                    "validation_error": err,
                    "source": "filesystem",
                }
            )

    merged: dict[str, dict[str, Any]] = {}
    for item in filesystem + skills:
        merged[item["name"]] = {**item, "in_database": item["name"] in db_rows}
    for proj in projects:
        key = proj["name"]
        if key in merged:
            merged[key] = {**merged[key], **proj}
        else:
            merged[key] = {**proj, "in_database": key in db_rows}
    for name, row in db_rows.items():
        if name not in merged:
            merged[name] = {**row, "in_database": True, "valid": None, "missing_file": True}

    return {
        "success": True,
        "registry_path": str(REGISTRY_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "ravenna_specialty": "agent-creation",
        "archetypes": list_archetypes()["archetypes"],
        "supervisors": registry.get("supervisors", []),
        "agents": list(merged.values()),
        "projects": projects,
        "counts": {
            "filesystem": len(filesystem) + len(skills),
            "projects": len(projects),
            "database": len(db_rows),
            "merged": len(merged),
        },
    }


def validate_agent_definition(path: str) -> dict[str, Any]:
    rel = path.replace("\\", "/").lstrip("/")
    file_path = PROJECT_ROOT / rel
    if not file_path.is_file():
        return {"success": False, "valid": False, "error": f"arquivo não encontrado: {rel}"}

    text = file_path.read_text(encoding="utf-8")
    meta, err = _parse_frontmatter(text)
    issues: list[str] = []
    warnings: list[str] = []

    if err:
        issues.append(err)
    else:
        if not meta.get("name"):
            issues.append("campo 'name' ausente no frontmatter")
        if not meta.get("description"):
            issues.append("campo 'description' ausente no frontmatter")
        name = str(meta.get("name", ""))
        if file_path.parent.name == "agents" and file_path.suffix == ".md":
            if name and name != file_path.stem:
                warnings.append(f"name '{name}' difere do arquivo '{file_path.stem}'")
        if "Aprendizado contínuo" not in text and file_path.parent.name == "agents":
            warnings.append("seção de aprendizado contínuo ausente — use scaffold_agent_project")
        if len(text.strip()) < 200:
            warnings.append("corpo curto — agentes completos devem ter domínios, fluxo e aprendizado")

    kind = "cursor_skill" if file_path.name == "SKILL.md" else "cursor_subagent"
    project_manifest = None
    if kind == "cursor_subagent" and meta.get("name"):
        manifest_path = PROJECTS_DIR / str(meta.get("name")) / "manifest.yaml"
        if manifest_path.is_file():
            with manifest_path.open(encoding="utf-8") as fh:
                project_manifest = yaml.safe_load(fh)

    return {
        "success": True,
        "valid": len(issues) == 0,
        "path": rel,
        "kind": kind,
        "name": meta.get("name"),
        "description": meta.get("description"),
        "issues": issues,
        "warnings": warnings,
        "project": project_manifest,
    }


def scaffold_cursor_agent(
    name: str,
    description: str,
    focus: str,
    *,
    archetype: str = "custom",
    triggers: str = "Quando o usuário pedir ajuda neste domínio.",
    display_name: str = "",
    parent_agent: str = "ravenna",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Atalho: cria projeto completo de agente (recomendado) ou delega ao arquétipo."""
    if archetype and archetype != "minimal":
        return scaffold_agent_project(
            name,
            archetype,
            description,
            focus=focus,
            triggers=triggers,
            display_name=display_name,
            parent_agent=parent_agent,
            overwrite=overwrite,
        )

    slug = _slug(name)
    if not _NAME_RE.match(slug):
        return {
            "success": False,
            "error": "name deve ser kebab-case (a-z, 0-9, hífen), 2–49 caracteres",
        }

    return scaffold_agent_project(
        slug,
        "custom",
        description,
        focus=focus,
        triggers=triggers,
        display_name=display_name,
        parent_agent=parent_agent,
        overwrite=overwrite,
    )


def scaffold_skill(
    name: str,
    description: str,
    focus: str,
    *,
    triggers: str = "Quando o cenário descrito no skill se aplicar.",
    display_name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    slug = _slug(name)
    if not _NAME_RE.match(slug):
        return {
            "success": False,
            "error": "name deve ser kebab-case (a-z, 0-9, hífen), 2–49 caracteres",
        }

    skill_dir = SKILLS_DIR / slug
    file_path = skill_dir / "SKILL.md"
    if file_path.exists() and not overwrite:
        return {
            "success": False,
            "error": f"skill já existe: {file_path.relative_to(PROJECT_ROOT)}",
            "hint": "use overwrite=true para substituir",
        }

    skill_dir.mkdir(parents=True, exist_ok=True)
    label = display_name.strip() or slug.replace("-", " ").title()
    body = f"""# {label}

## Objetivo

{focus.strip() or "workflow especializado"}

## Quando usar

{triggers.strip()}

## Fluxo

1. Entenda o pedido do usuário e o contexto do projeto
2. Execute o workflow com passos claros e verificáveis
3. `add_learning_note` ao aprender algo novo

## Aprendizado

- Início: `search_knowledge` + `get_context_for_task`
- Fim: `add_learning_note` + `record_session`
"""
    desc_wrapped = description.strip().replace("\n", " ")
    content = f"---\nname: {slug}\ndescription: >-\n  {desc_wrapped}\n---\n\n{body.strip()}\n"
    file_path.write_text(content, encoding="utf-8")

    validation = validate_agent_definition(str(file_path.relative_to(PROJECT_ROOT)))
    registration = _register_agent(
        name=slug,
        kind="cursor_skill",
        file_path=file_path,
        description=desc_wrapped,
        role=focus.strip(),
        tags=["user-skill", "cursor-skill", "learning"],
    )

    return {
        "success": True,
        "created": True,
        "name": slug,
        "file_path": registration["file_path"],
        "validation": validation,
        "next_steps": [
            f"Skill disponível em `.cursor/skills/{slug}/SKILL.md`",
            "Inclui loop de aprendizado básico",
        ],
    }
