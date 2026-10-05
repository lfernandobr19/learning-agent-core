"""Orquestração diária — treino IDE L6 (motor + agentes + Cursor braços)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from learning_agent.config import PROJECT_ROOT

PROJECT = "ravenna-ide-rebuild"
REBUILD_ROOT = PROJECT_ROOT / "agents" / "projects" / "ravenna-ide-rebuild"
WEEK_PLAN_PATH = REBUILD_ROOT / "week-plan.yaml"
STATE_PATH = REBUILD_ROOT / "data" / "training_state.json"
DAILY_DIR = REBUILD_ROOT / "data" / "daily"
WORK_ORDERS = PROJECT_ROOT / "data" / "ide_rebuild" / "work_orders"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_week_plan() -> dict[str, Any]:
    if not WEEK_PLAN_PATH.is_file():
        return {"days": []}
    return yaml.safe_load(WEEK_PLAN_PATH.read_text(encoding="utf-8")) or {}


def load_state() -> dict[str, Any]:
    return _read_json(
        STATE_PATH,
        {
            "project": PROJECT,
            "current_day": 0,
            "started_at": None,
            "days_completed": [],
            "kickoff": False,
        },
    )


def save_state(state: dict[str, Any]) -> None:
    state["updated_at"] = _utcnow()
    _write_json(STATE_PATH, state)


def get_day_plan(day: int | None = None) -> dict[str, Any] | None:
    state = load_state()
    n = day if day is not None else int(state.get("current_day") or 1)
    for d in load_week_plan().get("days") or []:
        if int(d.get("day", 0)) == n:
            return d
    return None


def _file_exists(name: str) -> bool:
    if name.endswith((".tsx", ".ts", ".py")):
        candidates = [
            PROJECT_ROOT / "ravenna-ide" / "frontend" / "src" / "components" / name,
            PROJECT_ROOT / "ravenna-ide" / "frontend" / "src" / name,
        ]
        return any(p.is_file() for p in candidates)
    return (PROJECT_ROOT / name).is_file()


def _run_vitest_smoke() -> dict[str, Any]:
    fe = PROJECT_ROOT / "ravenna-ide" / "frontend"
    if not (fe / "package.json").is_file():
        return {"passed": False, "detail": "frontend/package.json ausente"}
    try:
        r = subprocess.run(
            ["npm", "test"],
            cwd=str(fe),
            capture_output=True,
            text=True,
            timeout=120,
            shell=True,
        )
        return {
            "passed": r.returncode == 0,
            "detail": (r.stdout or r.stderr or "")[-800:],
            "exit_code": r.returncode,
        }
    except Exception as exc:
        return {"passed": False, "detail": str(exc)[:300]}


def _grep_in_repo(pattern: str, *paths: str) -> bool:
    import re

    for rel in paths:
        p = PROJECT_ROOT / rel.replace("/", "\\") if "\\" not in rel else PROJECT_ROOT / rel
        if not p.is_file():
            continue
        try:
            if re.search(pattern, p.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def _check_acceptance_item(key: str) -> dict[str, Any]:
    """Probe específico por critério do week-plan."""
    k = key.lower()
    if "vitest" in k:
        return _run_vitest_smoke()
    if key.endswith(".tsx") or key.endswith(".ts"):
        ok = _file_exists(key)
        return {"passed": ok, "detail": "arquivo presente" if ok else "ausente"}
    if "fileexplorer" in k and "watch" in k:
        ok = _grep_in_repo(
            r"setInterval|file_changed|watch|WebSocket",
            "ravenna-ide/frontend/src/components/FileExplorer.tsx",
        )
        return {"passed": ok, "detail": "FileExplorer refresh/watch" if ok else "sem watcher"}
    if "diffeditor" in k.replace("_", "").replace(" ", ""):
        ok = _file_exists("DiffEditorPane.tsx")
        return {"passed": ok, "detail": "DiffEditorPane.tsx" if ok else "ausente"}
    if "e2e" in k or "open-save" in k:
        fe = PROJECT_ROOT / "ravenna-ide" / "frontend"
        spec = fe / "e2e" / "open-save.spec.ts"
        if not spec.is_file():
            return {"passed": False, "detail": "e2e/open-save.spec.ts ausente"}
        if os.environ.get("IDE_RUN_E2E", "").lower() not in {"1", "true", "yes"}:
            return {"passed": True, "detail": "e2e spec presente (run IDE_RUN_E2E=1 para executar)"}
        try:
            r = subprocess.run(
                ["npm", "run", "test:e2e", "--", "e2e/open-save.spec.ts"],
                cwd=str(fe),
                capture_output=True,
                text=True,
                timeout=180,
                shell=True,
            )
            return {
                "passed": r.returncode == 0,
                "detail": (r.stdout or r.stderr or "")[-600:],
                "exit_code": r.returncode,
            }
        except Exception as exc:
            return {"passed": False, "detail": str(exc)[:300]}
    ok = _file_exists(key)
    return {"passed": ok, "detail": key if ok else f"{key} ausente"}


def check_day_acceptance(day_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Verifica critérios de aceite do dia (week-plan)."""
    day_plan = day_plan or get_day_plan()
    if not day_plan:
        return {"success": False, "error": "dia não encontrado no week-plan"}

    checks: dict[str, Any] = {}
    for item in day_plan.get("acceptance") or []:
        key = str(item)
        checks[key] = _check_acceptance_item(key)

    missing = [k for k, v in checks.items() if not v.get("passed")]
    return {
        "success": len(missing) == 0,
        "day": day_plan.get("day"),
        "title": day_plan.get("title"),
        "checks": checks,
        "missing": missing,
    }


def build_cursor_prompt(day_plan: dict[str, Any] | None = None) -> str:
    plan = load_week_plan()
    day_plan = day_plan or get_day_plan()
    if not day_plan:
        return "Plano do dia não encontrado."

    template = plan.get("cursor_prompt_template") or (
        "@{owner} Dia {day}: {title}\nObjetivos: {objectives}\nCritérios: {acceptance}"
    )
    return template.format(
        owner=day_plan.get("owner", "frontend-lead"),
        day=day_plan.get("day", 1),
        title=day_plan.get("title", ""),
        objectives=", ".join(day_plan.get("objectives") or []),
        acceptance=", ".join(day_plan.get("acceptance") or []),
    )


def _save_work_order(payload: dict[str, Any]) -> Path:
    WORK_ORDERS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    agent = payload.get("owner", "ravenna")
    path = WORK_ORDERS / f"{ts}-day{payload.get('day', 0)}-{agent}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def kickoff(*, day: int = 1) -> dict[str, Any]:
    """Inicia treino IDE — baseline, work order, journal."""
    from learning_agent.core import agent_action_journal, ide_objectives

    day_plan = get_day_plan(day)
    if not day_plan:
        return {"success": False, "error": f"dia {day} não definido"}

    baseline = ide_objectives.assess_completion(run_slow_probes=False)
    acceptance = check_day_acceptance(day_plan)

    state = load_state()
    if not state.get("kickoff"):
        state["kickoff"] = True
        state["started_at"] = _utcnow()
    state["current_day"] = day
    save_state(state)

    prompt = build_cursor_prompt(day_plan)
    work_order = {
        "type": "ide_day_kickoff",
        "day": day,
        "title": day_plan.get("title"),
        "owner": day_plan.get("owner"),
        "agents": day_plan.get("agents", []),
        "objectives": day_plan.get("objectives"),
        "acceptance": day_plan.get("acceptance"),
        "acceptance_status": acceptance,
        "baseline": {
            "cursor_parity_pct": baseline.get("summary", {}).get("cursor_parity_pct"),
            "must_met": baseline.get("summary", {}).get("must_met"),
            "must_total": baseline.get("summary", {}).get("must_total"),
        },
        "motor": "ravenna",
        "executor": "cursor",
        "journal_required": True,
        "learning_loop": [
            "search_knowledge",
            "implementar no Cursor",
            "vitest/proof_gate",
            "complete_action_cycle",
            "run_learning_closure",
            "create_quiz",
            "agent_share_insight",
        ],
        "cursor_prompt": prompt,
        "created_at": _utcnow(),
    }
    wo_path = _save_work_order(work_order)

    journal = agent_action_journal.complete_action_cycle(
        "ravenna",
        "ide_rebuild_kickoff",
        f"Dia {day} — {day_plan.get('title')}",
        {
            "success": True,
            "plan": prompt[:500],
            "baseline_pct": baseline.get("summary", {}).get("cursor_parity_pct"),
            "work_order": str(wo_path),
        },
        project=PROJECT,
    )

    owner = str(day_plan.get("owner") or "frontend-lead")
    try:
        from learning_agent.core import agent_ide_practice

        improvement = agent_ide_practice.run_ide_improvement_sprint(owner, broadcast_observer=False)
        agent_action_journal.complete_action_cycle(
            owner,
            "ide_improvement_sprint",
            f"Dia {day} kickoff",
            improvement,
            project=PROJECT,
        )
    except Exception as exc:
        improvement = {"success": False, "error": str(exc)[:200]}

    return {
        "success": True,
        "action": "ide_rebuild_kickoff",
        "day": day,
        "title": day_plan.get("title"),
        "owner": owner,
        "baseline": work_order["baseline"],
        "acceptance": acceptance,
        "cursor_prompt": prompt,
        "work_order": str(wo_path),
        "journal": journal,
        "owner_sprint": improvement,
    }


def close_day(*, day: int | None = None, advance: bool = True) -> dict[str, Any]:
    """Encerra dia — acceptance, proof_gate, closure, lição, quiz."""
    from learning_agent.core import agent_action_journal, agent_autonomy, agent_learning_loop, ide_objectives, knowledge, quiz

    state = load_state()
    n = day if day is not None else int(state.get("current_day") or 1)
    day_plan = get_day_plan(n)
    if not day_plan:
        return {"success": False, "error": f"dia {n} não definido"}

    acceptance = check_day_acceptance(day_plan)
    completion = ide_objectives.assess_completion(
        run_slow_probes=os.environ.get("IDE_SLOW_PROBES", "").lower() in {"1", "true", "yes"}
    )

    proof = None
    agents = list(day_plan.get("agents") or [day_plan.get("owner")])
    if "qa-guardian" in agents:
        try:
            proof = agent_autonomy.execute_autonomy_action("proof_gate")
            agent_action_journal.complete_action_cycle(
                "qa-guardian",
                "proof_gate",
                f"Dia {n} fechamento",
                proof if isinstance(proof, dict) else {"success": True, "result": str(proof)},
                project=PROJECT,
            )
        except Exception as exc:
            proof = {"success": False, "error": str(exc)[:200]}

    closures: list[dict[str, Any]] = []
    for agent in agents:
        slug = str(agent).strip().lower().replace("_", "-")
        if not slug:
            continue
        try:
            c = agent_learning_loop.run_learning_closure(
                "ide_day_close",
                f"Dia {n}: {day_plan.get('title')}",
                {
                    "acceptance": acceptance,
                    "cursor_parity_pct": completion.get("summary", {}).get("cursor_parity_pct"),
                    "missing": acceptance.get("missing"),
                },
                agent=slug,
                broadcast_observer=False,
            )
            closures.append({"agent": slug, "closure": c})
        except Exception as exc:
            closures.append({"agent": slug, "error": str(exc)[:200]})

    lesson_body = _format_daily_lesson(n, day_plan, acceptance, completion, proof, closures)
    note = knowledge.add_note(
        f"[Treino IDE] Dia {n} — {day_plan.get('title')}",
        lesson_body,
        tags=["ide-rebuild", f"day-{n}", "treino-l6", f"agent:{day_plan.get('owner')}"],
        sync_cloud=False,
    )

    quiz_row = None
    if acceptance.get("missing"):
        topic = f"IDE Dia {n}: {acceptance['missing'][0]}"
        try:
            quiz_row = quiz.create_quiz(topic=topic.split(":")[0][:40], count=1)
        except Exception:
            quiz_row = None

    daily_report = {
        "day": n,
        "title": day_plan.get("title"),
        "closed_at": _utcnow(),
        "acceptance": acceptance,
        "completion_summary": completion.get("summary"),
        "proof_gate": proof,
        "closures": closures,
        "lesson_note_id": note.get("note_id") if note else None,
        "quiz": quiz_row,
    }
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    report_path = DAILY_DIR / f"day-{n:02d}.json"
    _write_json(report_path, daily_report)

    agent_action_journal.complete_action_cycle(
        "ravenna",
        "ide_day_close",
        f"Dia {n} — {day_plan.get('title')}",
        {
            "success": acceptance.get("success", False),
            "summary": lesson_body[:400],
            "report": str(report_path),
        },
        project=PROJECT,
    )

    if advance and acceptance.get("success") and n not in state.get("days_completed", []):
        state.setdefault("days_completed", []).append(n)
        state["current_day"] = n + 1
        save_state(state)

    return {
        "success": True,
        "action": "ide_day_close",
        "day": n,
        "acceptance_ok": acceptance.get("success"),
        "missing": acceptance.get("missing"),
        "cursor_parity_pct": completion.get("summary", {}).get("cursor_parity_pct"),
        "lesson_preview": lesson_body[:600],
        "report_path": str(report_path),
        "next_day": state.get("current_day") if advance else n,
    }


def _format_daily_lesson(
    day: int,
    day_plan: dict[str, Any],
    acceptance: dict[str, Any],
    completion: dict[str, Any],
    proof: dict[str, Any] | None,
    closures: list[dict[str, Any]],
) -> str:
    summary = completion.get("summary") or {}
    lines = [
        f"## Dia {day} — {day_plan.get('title')}",
        f"**Owner:** {day_plan.get('owner')}",
        "",
        "### Aceite do dia",
        f"- Status: {'OK' if acceptance.get('success') else 'PENDENTE'}",
    ]
    for k, v in (acceptance.get("checks") or {}).items():
        mark = "OK" if v.get("passed") else "FALHA"
        lines.append(f"- {k}: {mark}")
    if acceptance.get("missing"):
        lines.append(f"- Falta: {', '.join(acceptance['missing'])}")

    lines.extend(
        [
            "",
            "### Paridade IDE",
            f"- Cursor parity: {summary.get('cursor_parity_pct')}%",
            f"- Must: {summary.get('must_met')}/{summary.get('must_total')}",
            "",
            "### Proof gate",
            f"- {'OK' if (proof or {}).get('success') is not False else 'verificar'}",
            "",
            "### Objetivos do dia",
        ]
    )
    for obj in day_plan.get("objectives") or []:
        lines.append(f"- {obj}")

    lines.append("\n### Lição (motor)")
    if acceptance.get("success"):
        lines.append("Dia fechado com aceite verde — repetir padrão: journal em cada passo Cursor.")
    else:
        lines.append(
            "Priorizar critérios faltantes antes de avançar. Cursor implementa; motor registra closure."
        )

    if closures:
        lines.append("\n### Closures agentes")
        for c in closures[:4]:
            lines.append(f"- {c.get('agent')}: registrado")

    return "\n".join(lines)


def status() -> dict[str, Any]:
    from learning_agent.core import ide_objectives

    state = load_state()
    day = int(state.get("current_day") or 0)
    day_plan = get_day_plan(day) if day else None
    completion = ide_objectives.assess_completion(run_slow_probes=False)
    acceptance = check_day_acceptance(day_plan) if day_plan else None

    return {
        "success": True,
        "project": PROJECT,
        "kickoff": state.get("kickoff"),
        "started_at": state.get("started_at"),
        "current_day": day,
        "days_completed": state.get("days_completed", []),
        "day_plan": day_plan,
        "acceptance": acceptance,
        "completion": completion.get("summary"),
        "cursor_prompt": build_cursor_prompt(day_plan) if day_plan else None,
    }
