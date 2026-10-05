"""Roteamento de delegação — escolhe subagente especialista para uma tarefa."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT

PROJECTS_DIR = PROJECT_ROOT / "agents" / "projects"

ARCHETYPE_KEYWORDS: dict[str, list[str]] = {
    "backend": [
        "api",
        "fastapi",
        "endpoint",
        "sqlite",
        "websocket",
        "pytest",
        "backend",
        "servidor",
        "pydantic",
        "uvicorn",
        "python",
        "router",
        "sqlalchemy",
    ],
    "frontend": [
        "react",
        "tsx",
        "component",
        "css",
        "ui",
        "vitest",
        "frontend",
        "typescript",
        "a11y",
        "webview",
        "vite",
        "remote_app",
    ],
    "qa-inspector": [
        "test",
        "teste",
        "qa",
        "e2e",
        "spec",
        "coverage",
        "cobertura",
        "regressão",
        "smoke",
        "vitest",
        "pytest",
    ],
    "data": [
        "pipeline",
        "etl",
        "sql",
        "databricks",
        "data",
        "warehouse",
        "parquet",
        "spark",
        "dbt",
    ],
    "reliability": [
        "debug",
        "log",
        "erro",
        "crash",
        "performance",
        "reliability",
        "observability",
        "sentry",
        "latência",
        "timeout",
    ],
    "finance": [
        "fii",
        "invest",
        "finance",
        "mercado",
        "ação",
        "carteira",
        "dividendo",
        "p/vp",
        "bolsa",
    ],
    "custom": [
        "ide",
        "vscode",
        "extension",
        "cursor",
        "vsix",
        "webview",
        "paridade",
    ],
}


def _tokenize(text: str) -> set[str]:
    raw = text.lower().replace("/", " ").replace("_", " ").replace("-", " ")
    return {w for w in raw.split() if len(w) > 2}


def load_project_agents() -> list[dict[str, Any]]:
    agents: list[dict[str, Any]] = []
    if not PROJECTS_DIR.is_dir():
        return agents
    for manifest_file in sorted(PROJECTS_DIR.glob("*/manifest.yaml")):
        with manifest_file.open(encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}
        if not isinstance(manifest, dict):
            continue
        learning = manifest.get("learning") or {}
        tags = learning.get("tags") if isinstance(learning, dict) else []
        agents.append(
            {
                "name": manifest.get("name", manifest_file.parent.name),
                "display_name": manifest.get("display_name", manifest_file.parent.name),
                "archetype": manifest.get("archetype", "custom"),
                "description": manifest.get("description", ""),
                "focus": manifest.get("focus", ""),
                "tags": tags if isinstance(tags, list) else [],
            }
        )
    return agents


def score_agent(agent: dict[str, Any], text: str, tokens: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    slug = str(agent.get("name") or "")
    display = str(agent.get("display_name") or slug)

    for part in slug.replace("_", "-").split("-"):
        if part and part in text:
            score += 2.5
            reasons.append(part)

    if slug.replace("_", "-") in text.replace("_", "-"):
        score += 3.0
        reasons.append(slug)

    for field in (agent.get("focus"), agent.get("description")):
        if not field:
            continue
        for word in _tokenize(str(field)):
            if word in tokens:
                score += 0.75
                if word not in reasons:
                    reasons.append(word)

    for tag in agent.get("tags") or []:
        tag_l = str(tag).lower()
        if tag_l in text or tag_l in tokens:
            score += 1.25
            if tag_l not in reasons:
                reasons.append(tag_l)

    archetype = str(agent.get("archetype") or "custom")
    for kw in ARCHETYPE_KEYWORDS.get(archetype, ARCHETYPE_KEYWORDS["custom"]):
        if kw in text:
            score += 1.0
            if kw not in reasons:
                reasons.append(kw)

    if display.lower() in text:
        score += 2.0
        reasons.append(display)

    return score, reasons[:8]


def suggest_delegate(
    message: str,
    context: str = "",
    *,
    min_score: float = 2.0,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """Sugere subagente para delegar. Retorna agent=None se Ravenna deve responder."""
    combined = f"{message}\n{context}".strip()
    text = combined.lower()
    tokens = _tokenize(combined)
    excluded = {e.strip().lower() for e in (exclude or [])}

    ranked: list[tuple[float, dict[str, Any], list[str]]] = []
    for agent in load_project_agents():
        slug = str(agent.get("name") or "")
        if slug.lower() in excluded:
            continue
        score, reasons = score_agent(agent, text, tokens)
        if score > 0:
            ranked.append((score, agent, reasons))

    ranked.sort(key=lambda x: x[0], reverse=True)

    if not ranked or ranked[0][0] < min_score:
        return {
            "agent": None,
            "display_name": None,
            "confidence": 0.0,
            "reason": "Nenhum especialista com match forte — Ravenna responde",
            "alternates": [
                {
                    "agent": a["name"],
                    "display_name": a.get("display_name"),
                    "score": s,
                }
                for s, a, _ in ranked[:3]
            ],
        }

    best_score, best, reasons = ranked[0]
    confidence = min(best_score / 10.0, 1.0)
    return {
        "agent": best["name"],
        "display_name": best.get("display_name"),
        "archetype": best.get("archetype"),
        "focus": best.get("focus"),
        "confidence": round(confidence, 3),
        "score": round(best_score, 2),
        "reason": ", ".join(reasons) if reasons else best.get("focus", ""),
        "alternates": [
            {
                "agent": a["name"],
                "display_name": a.get("display_name"),
                "score": round(s, 2),
            }
            for s, a, _ in ranked[1:4]
        ],
    }


def agent_exists(slug: str) -> bool:
    if not slug.strip():
        return False
    normalized = slug.strip().lower().replace("_", "-")
    return any(a["name"] == normalized for a in load_project_agents())
