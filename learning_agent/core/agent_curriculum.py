"""Currículo por agente — marcos até nível 5."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_capability

CURRICULA_DIR = PROJECT_ROOT / "agents" / "curricula"


def get_stored_curriculum_level(agent: str) -> int:
    """Nível de currículo persistido (overnight/state) — sem recalcular capability."""
    slug = agent.strip().lower().replace("_", "-")
    candidates = [
        PROJECT_ROOT / "data" / f"{slug.replace('-', '_')}_overnight_last.json",
        PROJECT_ROOT / "data" / f"{slug}_curriculum_progress.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            level = data.get("curriculum_level") or data.get("current_level")
            if level is not None:
                return int(level)
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return 0


def load_agent_curriculum(agent: str) -> dict[str, Any]:
    slug = agent.strip().lower().replace("_", "-")
    path = CURRICULA_DIR / f"{slug}.yaml"
    if not path.is_file():
        return {"success": False, "error": f"currículo não encontrado: {slug}"}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {"success": True, "agent": slug, **data}


def list_curricula() -> dict[str, Any]:
    items = []
    for path in sorted(CURRICULA_DIR.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        items.append({"agent": data.get("agent", path.stem), "title": data.get("title", "")})
    return {"success": True, "curricula": items, "count": len(items)}


def get_next_milestone(agent: str) -> dict[str, Any]:
    stored = get_stored_curriculum_level(agent)
    if agent_capability.capability_compute_depth() > 0:
        current = stored or 1
    else:
        cap = agent_capability.compute_agent_capability(agent)
        current = max(stored, int(cap.get("level", 1) or 1)) if stored else cap.get("level", 1)
    cur = load_agent_curriculum(agent)
    if not cur.get("success"):
        return cur

    milestones = cur.get("milestones", [])
    target = next((m for m in milestones if m.get("level", 0) > current), None)
    if not target:
        target = milestones[-1] if milestones else {}

    return {
        "success": True,
        "agent": agent,
        "current_level": current,
        "target_level": target.get("level"),
        "milestone": target,
        "suggested_actions": target.get("actions", []),
        "ide_practice": cur.get("ide_practice", {}),
    }
