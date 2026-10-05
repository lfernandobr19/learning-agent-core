"""Práticas na IDE — cada agente busca melhorias na ferramenta no seu domínio."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from learning_agent.config import IDE_IMPROVEMENTS_DIR, PROJECT_ROOT
from learning_agent.core import agent_collaboration, codebase, knowledge, llm as llm_core

from learning_agent.core.agent_curriculum import load_agent_curriculum


def _llm(system: str, user: str, *, max_tokens: int = 400) -> str:
    try:
        reply, _ = llm_core.chat_with_fallback(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.55,
        )
        return reply
    except Exception:
        return "(análise IDE — modelo indisponível)"


def _scan_focus_paths(paths: list[str], limit: int = 4) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for rel in paths[:6]:
        clean = rel.replace("**", "").strip("/")
        if "frontend" in clean:
            root = PROJECT_ROOT / "ravenna-ide" / "frontend" / "src"
            sub = clean.split("frontend/src/")[-1] if "frontend/src/" in clean else "components"
            target = root / sub
        else:
            target = PROJECT_ROOT / clean

        if target.is_file():
            text = target.read_text(encoding="utf-8", errors="replace")[:1200]
            snippets.append({"path": str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"), "snippet": text})
        elif target.is_dir():
            for f in sorted(target.rglob("*"))[:20]:
                if f.suffix in {".py", ".tsx", ".ts", ".css"} and f.is_file():
                    snippets.append({
                        "path": str(f.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "snippet": f.read_text(encoding="utf-8", errors="replace")[:800],
                    })
                if len(snippets) >= limit:
                    break
        if len(snippets) >= limit:
            break

    if not snippets:
        hits = codebase.search_code("ObserverPanel AgentsPanel api.ts", limit=3)
        for h in hits:
            snippets.append({
                "path": h.get("metadata", {}).get("path", "code"),
                "snippet": str(h.get("content", ""))[:800],
            })
    return snippets[:limit]


def run_ide_improvement_sprint(
    agent_name: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """
    Agente analisa a Ravenna IDE e propõe melhorias no seu domínio.
    Válido: cada especialista evolui a ferramenta que usa para praticar.
    """
    from learning_agent.core.agent_capability import CORE_AGENTS

    slug = agent_name or CORE_AGENTS[1]
    cur = load_agent_curriculum(slug)
    ide_cfg = cur.get("ide_practice", {}) if cur.get("success") else {}
    paths = ide_cfg.get("focus_paths", ["ravenna-ide/frontend/src/components/"])
    themes = ide_cfg.get("improvement_themes", ["UX da IDE", "observabilidade"])

    manifest = agent_collaboration._load_manifest(slug) or {}
    display = manifest.get("display_name", slug)
    snippets = _scan_focus_paths(paths)

    context = "\n\n".join(f"### {s['path']}\n```\n{s['snippet'][:600]}\n```" for s in snippets)
    themes_txt = "\n".join(f"- {t}" for t in themes)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug,
            f"Prática na IDE: analisando {len(snippets)} arquivo(s)…",
            level="ide-practice",
        )

    proposal = _llm(
        f"Você é {display}. Analise a Ravenna IDE e proponha 3-5 melhorias CONCRETAS "
        f"no código/UI relacionadas ao seu domínio. Formato markdown com: problema, solução, "
        f"arquivo alvo, como testar.",
        f"Temas do agente:\n{themes_txt}\n\nTrechos:\n{context}",
        max_tokens=500,
    )

    IDE_IMPROVEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    thread_id = f"ide-{uuid.uuid4().hex[:10]}"
    out_file = IDE_IMPROVEMENTS_DIR / f"{slug}-{thread_id}.md"
    body = (
        f"# Melhorias IDE — {display}\n\n"
        f"**ID:** {thread_id}\n**Agente:** {slug}\n\n"
        f"## Temas\n{themes_txt}\n\n"
        f"## Proposta\n{proposal}\n\n"
        f"## Arquivos analisados\n"
        + "\n".join(f"- {s['path']}" for s in snippets)
    )
    out_file.write_text(body, encoding="utf-8")

    knowledge.add_note(
        f"[IDE] {display} — melhorias propostas",
        body[:3000],
        tags=["ide-practice", f"agent:{slug}", "ravenna-ide"],
    )
    agent_collaboration.share_insight(slug, proposal[:500], "ide-improvement", to_agents=["all", "ravenna"])

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            slug, f"Proposta IDE: {proposal[:180]}…", level="ide-proposal"
        )

    return {
        "success": True,
        "action": "ide_improvement_sprint",
        "agent": slug,
        "thread_id": thread_id,
        "proposal": proposal,
        "files_analyzed": [s["path"] for s in snippets],
        "output_file": str(out_file.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "valid_practice": True,
        "rationale": "Agentes praticam evoluindo a própria IDE no domínio de cada um.",
    }
