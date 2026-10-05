"""Pipeline Ship — fila mergeável e métricas de integração."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT

SHIP_ROOT = PROJECT_ROOT / "agents" / "ship"
QUEUE_DIR = SHIP_ROOT / "queue"
DONE_DIR = SHIP_ROOT / "done"
OPERATING_MODE = SHIP_ROOT / "operating_mode.yaml"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_operating_mode() -> dict[str, Any]:
    if not OPERATING_MODE.is_file():
        return {}
    return yaml.safe_load(OPERATING_MODE.read_text(encoding="utf-8")) or {}


def _load_yaml_files(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            data["_file"] = path.name
            data["_path"] = str(path.relative_to(PROJECT_ROOT))
            items.append(data)
        except yaml.YAMLError:
            continue
    return items


def list_queue() -> list[dict[str, Any]]:
    return _load_yaml_files(QUEUE_DIR)


def list_done(limit: int = 50) -> list[dict[str, Any]]:
    done = _load_yaml_files(DONE_DIR)
    done.sort(key=lambda x: x.get("merged_at") or "", reverse=True)
    return done[:limit]


def get_next_ready_item() -> dict[str, Any] | None:
    for item in list_queue():
        if (item.get("status") or "").lower() == "ready":
            return item
    return None


def ship_velocity(*, days: int = 14) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    done = list_done(limit=200)
    recent = []
    for item in done:
        merged = item.get("merged_at") or item.get("done_at")
        if not merged:
            continue
        try:
            dt = datetime.fromisoformat(str(merged).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt >= cutoff:
            recent.append(item)

    by_week: dict[str, int] = {}
    for item in recent:
        merged = item.get("merged_at") or item.get("done_at") or ""
        week = str(merged)[:10]
        by_week[week] = by_week.get(week, 0) + 1

    journal_actions = 0
    try:
        from learning_agent import db

        db.init_db()
        with db.get_connection() as conn:
            journal_actions = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM agent_action_log
                    WHERE substr(created_at, 1, 10) >= ?
                    """,
                    (cutoff.strftime("%Y-%m-%d"),),
                ).fetchone()[0]
            )
    except Exception:
        pass

    merges = len(recent)
    ratio = round(journal_actions / max(merges, 1), 1) if merges else float(journal_actions)

    return {
        "days": days,
        "merges": merges,
        "merges_per_week": round(merges / max(days / 7, 1), 2),
        "target_merges_per_week": load_operating_mode().get("ship", {}).get("target_merges_per_week", 2),
        "journal_actions": journal_actions,
        "train_to_ship_ratio": ratio,
        "healthy_ratio_max": 3.0,
        "alert": merges == 0 and journal_actions > 0,
        "timeline": [{"day": k, "merges": v} for k, v in sorted(by_week.items())],
        "recent": recent[:10],
    }


def build_ship_status() -> dict[str, Any]:
    queue = list_queue()
    done = list_done(limit=20)
    ready = [q for q in queue if (q.get("status") or "").lower() == "ready"]
    blocked = [q for q in queue if (q.get("status") or "").lower() == "blocked"]
    mode = load_operating_mode()

    return {
        "success": True,
        "operating_mode": mode,
        "queue_total": len(queue),
        "queue_ready": len(ready),
        "queue_blocked": len(blocked),
        "done_total": len(_load_yaml_files(DONE_DIR)),
        "next_item": get_next_ready_item(),
        "queue": queue,
        "done_recent": done,
        "velocity": ship_velocity(),
    }


def is_overnight_paused(kind: str) -> tuple[bool, str]:
    """Respeita operating_mode — foco finance-lead congela outros loops."""
    mode = load_operating_mode()
    frozen = set(mode.get("frozen") or [])
    focus = (mode.get("focus") or {}).get("primary_agent", "")
    if kind == "ide_rebuild" and "ide_full_parity" in frozen:
        return True, f"PAUSADO — foco em {focus} (ide_full_parity congelado)"
    if kind == "core_evolution" and "core_l6_sprints" in frozen:
        return True, f"PAUSADO — foco em {focus} (core_l6_sprints congelado)"
    if kind == "autonomy" and "autonomy_24_7" in frozen:
        return True, "PAUSADO — autonomy_24_7 congelado"
    return False, ""


def mark_done(
    item_id: str,
    *,
    commit: str = "",
    merged_at: str | None = None,
) -> dict[str, Any]:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)

    source: Path | None = None
    data: dict[str, Any] | None = None
    for path in QUEUE_DIR.glob("*.yaml"):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if doc.get("id") == item_id:
            source = path
            data = doc
            break

    if not source or not data:
        return {"success": False, "error": f"Item {item_id} não encontrado na fila"}

    data["status"] = "done"
    data["merged_at"] = merged_at or _utcnow()
    if commit:
        data["commit"] = commit

    dest_name = source.name
    dest = DONE_DIR / dest_name
    dest.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    source.unlink()
    return {"success": True, "item": data, "moved_to": str(dest.relative_to(PROJECT_ROOT))}
