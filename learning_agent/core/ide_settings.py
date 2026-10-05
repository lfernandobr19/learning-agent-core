"""Settings e keybindings da Ravenna IDE (JSON persistido)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR, PROJECT_ROOT

SETTINGS_PATH = DATA_DIR / "ravenna_ide_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "editor.fontSize": 13,
    "editor.tabSize": 2,
    "editor.wordWrap": "on",
    "workbench.colorTheme": "vs-dark",
}

DEFAULT_KEYBINDINGS: list[dict[str, str]] = [
    {"key": "Ctrl+S", "command": "file.save"},
    {"key": "Ctrl+Shift+P", "command": "workbench.action.showCommands"},
    {"key": "Ctrl+`", "command": "view.terminal"},
    {"key": "Ctrl+L", "command": "view.chat"},
]


def _read() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {"settings": DEFAULT_SETTINGS, "keybindings": DEFAULT_KEYBINDINGS}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {"settings": DEFAULT_SETTINGS, "keybindings": DEFAULT_KEYBINDINGS}


def _write(data: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_settings() -> dict[str, Any]:
    data = _read()
    return {
        "success": True,
        "settings": data.get("settings") or DEFAULT_SETTINGS,
        "keybindings": data.get("keybindings") or DEFAULT_KEYBINDINGS,
    }


def save_settings(*, settings: dict[str, Any], keybindings: list[dict[str, str]]) -> dict[str, Any]:
    _write({"settings": settings, "keybindings": keybindings})
    return {"success": True, "path": str(SETTINGS_PATH)}


def list_rules_and_skills() -> dict[str, Any]:
    rules: list[str] = []
    skills: list[str] = []
    for base in (PROJECT_ROOT / ".cursor" / "rules", PROJECT_ROOT / ".cursor" / "skills"):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in {".md", ".mdc", ".yaml", ".yml"}:
                rel = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
                if "rules" in base.parts:
                    rules.append(rel)
                else:
                    skills.append(rel)
    return {"success": True, "rules": rules, "skills": skills}
