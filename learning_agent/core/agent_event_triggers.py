"""Gatilhos por evento — autonomia reativa."""

from __future__ import annotations

import json
from typing import Any

from learning_agent.config import AUTONOMY_EVENTS_PATH
from learning_agent.core import agent_collaboration

EVENT_ACTION_MAP: dict[str, str] = {
    "test_failed": "error_roundtable",
    "proof_failed": "debug_sweep",
    "file_saved": "code_walk",
    "commit": "peer_review",
    "capability_stall": "mentor_session",
    "ide_change": "ide_improvement_sprint",
    "quiz_weak": "spaced_review",
}


def _load_events() -> list[dict[str, Any]]:
    if not AUTONOMY_EVENTS_PATH.is_file():
        return []
    try:
        with AUTONOMY_EVENTS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_events(events: list[dict[str, Any]]) -> None:
    AUTONOMY_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUTONOMY_EVENTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(events[-50:], fh, ensure_ascii=False, indent=2)


def emit_event(
    event_type: str,
    *,
    detail: str = "",
    agent: str = "",
    path: str = "",
) -> dict[str, Any]:
    """Registra evento para próximo ciclo autônomo."""
    from learning_agent import db

    payload = {
        "type": event_type,
        "detail": detail[:500],
        "agent": agent,
        "path": path,
        "created_at": db._utcnow(),
        "consumed": False,
    }
    events = _load_events()
    events.append(payload)
    _save_events(events)

    action = EVENT_ACTION_MAP.get(event_type, "research_gaps")
    agent_collaboration._broadcast_to_observer(
        "ravenna",
        f"Evento «{event_type}»: próxima ação sugerida → {action}",
        level="event-trigger",
    )
    return {"success": True, "event": payload, "suggested_action": action}


def pop_pending_event() -> dict[str, Any] | None:
    events = _load_events()
    for i, ev in enumerate(events):
        if not ev.get("consumed"):
            events[i] = {**ev, "consumed": True}
            _save_events(events)
            return ev
    return None


def pick_event_action() -> str | None:
    ev = pop_pending_event()
    if not ev:
        return None
    return EVENT_ACTION_MAP.get(ev.get("type", ""), "research_gaps")


def list_pending_events() -> dict[str, Any]:
    events = _load_events()
    pending = [e for e in events if not e.get("consumed")]
    return {"success": True, "pending": pending, "count": len(pending)}
