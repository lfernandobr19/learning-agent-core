"""Catálogo de plugins Ravenna (manifest JSON + enable/disable)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR, PROJECT_ROOT

PLUGINS_DIR = PROJECT_ROOT / "ravenna-ide" / "plugins"
STATE_PATH = DATA_DIR / "ravenna-plugins-state.json"


def _load_state() -> dict[str, bool]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {str(k): bool(v) for k, v in (data.get("enabled") or {}).items()}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(enabled: dict[str, bool]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"enabled": enabled}, indent=2), encoding="utf-8")


def _read_manifest(path: Path) -> dict[str, Any] | None:
    manifest = path / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    plugin_id = str(data.get("id") or path.name).strip()
    if not plugin_id:
        return None
    return {
        "id": plugin_id,
        "name": str(data.get("name") or plugin_id),
        "version": str(data.get("version") or "0.0.0"),
        "description": str(data.get("description") or ""),
        "publisher": str(data.get("publisher") or "ravenna"),
        "builtin": bool(data.get("builtin", False)),
    }


def list_plugins() -> list[dict[str, Any]]:
    enabled_map = _load_state()
    plugins: list[dict[str, Any]] = []

    if PLUGINS_DIR.is_dir():
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            manifest = _read_manifest(entry)
            if not manifest:
                continue
            pid = manifest["id"]
            default_enabled = bool(manifest.get("builtin", False))
            plugins.append(
                {
                    **manifest,
                    "enabled": enabled_map.get(pid, default_enabled),
                    "path": str(entry.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                }
            )

    # Built-ins sempre presentes mesmo sem pasta
    known_ids = {p["id"] for p in plugins}
    for builtin in (
        {
            "id": "ravenna.ravenna-ai",
            "name": "Ravenna AI",
            "version": "0.10.2",
            "description": "Chat, Agent multi-turn, diff, shell, delegação",
            "publisher": "ravenna",
            "builtin": True,
        },
        {
            "id": "ravenna.ravenna-core",
            "name": "Ravenna Core",
            "version": "0.1.0",
            "description": "Journal e comandos base Ravenna",
            "publisher": "ravenna",
            "builtin": True,
        },
    ):
        if builtin["id"] in known_ids:
            continue
        plugins.append(
            {
                **builtin,
                "enabled": enabled_map.get(builtin["id"], True),
                "path": None,
            }
        )

    return sorted(plugins, key=lambda p: (not p.get("builtin"), p["name"].lower()))


def set_plugin_enabled(plugin_id: str, enabled: bool) -> dict[str, Any]:
    pid = plugin_id.strip()
    if not pid:
        raise ValueError("plugin_id obrigatório")
    state = _load_state()
    state[pid] = enabled
    _save_state(state)
    for plugin in list_plugins():
        if plugin["id"] == pid:
            return plugin
    return {"id": pid, "enabled": enabled}
