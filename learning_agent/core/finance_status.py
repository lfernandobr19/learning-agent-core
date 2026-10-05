"""Status finance-lead para Telegram — foco QUALIDADE > QUANTIDADE."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_benchmarks, agent_external_completion

AGENT = "finance-lead"
LOG = PROJECT_ROOT / "data" / "finance_lead_overnight.log"
STATE = PROJECT_ROOT / "data" / "finance_lead_overnight_state.json"
LAST = PROJECT_ROOT / "data" / "finance_lead_overnight_last.json"
EXTERNAL_CACHE = PROJECT_ROOT / "data" / "finance_lead_external_cache.json"
STATUS_CACHE = PROJECT_ROOT / "data" / "finance_lead_status_cache.json"
CACHE_TTL_SEC = 3600


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _overnight_running() -> bool:
    try:
        import psutil
    except ImportError:
        return LOG.is_file() and (datetime.now().timestamp() - LOG.stat().st_mtime) < 1200
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "run_finance_lead_overnight" in cmd:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _log_end_time() -> str | None:
    if not LOG.is_file():
        return None
    for line in reversed(LOG.read_text(encoding="utf-8", errors="replace").splitlines()):
        if "até 20" in line and "Início overnight" in line:
            # ex: Início overnight finance-lead — até 2026-06-11T05:30 max_cycles=0
            if "até " in line:
                return line.split("até ", 1)[1].split(" max_cycles", 1)[0].strip()
    return None


def _load_external_cache() -> dict[str, Any] | None:
    cached = _read_json(EXTERNAL_CACHE)
    if not cached or "assessed_at" not in cached:
        return None
    try:
        assessed = datetime.fromisoformat(cached["assessed_at"])
    except ValueError:
        return None
    if (datetime.now() - assessed).total_seconds() > CACHE_TTL_SEC:
        return None
    return cached.get("external")


def _save_external_cache(external: dict[str, Any]) -> None:
    EXTERNAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    EXTERNAL_CACHE.write_text(
        json.dumps({"assessed_at": datetime.now().isoformat(timespec="seconds"), "external": external}),
        encoding="utf-8",
    )


def _external_assessment(*, use_cache: bool) -> dict[str, Any]:
    if use_cache:
        return _load_external_cache() or {}
    external = agent_external_completion.assess_external_completion(AGENT)
    if external.get("success"):
        _save_external_cache(external)
    return external


def _status_from_parts(
    training: dict[str, Any],
    external: dict[str, Any],
    *,
    blind_score: float | None = None,
) -> dict[str, Any]:
    last = _read_json(LAST) or {}
    criteria_ok = [c for c in (external.get("criteria") or []) if c.get("passed")]
    criteria_fail = [c for c in (external.get("criteria") or []) if not c.get("passed")]
    if blind_score is None:
        blind_info = agent_benchmarks.benchmark_summary(AGENT)
        blind_score = blind_info.get("best_score_pct", 0)
        blind_runs = blind_info.get("runs_count", 0)
    else:
        blind_runs = None

    return {
        **training,
        "running": _overnight_running(),
        "end_at": _log_end_time(),
        "criteria_ok": criteria_ok,
        "criteria_fail": criteria_fail,
        "blind_runs": blind_runs,
        "blind_score": blind_score,
        "level": training.get("capability_level"),
        "score": training.get("capability_score"),
        "last_topic": (last.get("teacher_topic") or "")[:120],
        "pairs_after": last.get("pairs_after"),
        "teacher_distilled": last.get("teacher_distilled"),
        "study_distilled": last.get("study_distilled"),
        "readiness_pct": last.get("readiness_pct"),
        "training_examples": last.get("training_examples"),
        "curriculum_level": last.get("curriculum_level"),
        "curriculum_target": last.get("target_level"),
    }


def _save_status_cache(status: dict[str, Any], cap: dict[str, Any] | None = None) -> None:
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "capability": cap or {},
    }
    STATUS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_status_cache() -> dict[str, Any] | None:
    cached = _read_json(STATUS_CACHE)
    if not cached:
        return None
    try:
        updated = datetime.fromisoformat(str(cached.get("updated_at", "")))
    except ValueError:
        return None
    if (datetime.now() - updated).total_seconds() > CACHE_TTL_SEC:
        return None
    return cached.get("status")


def refresh_finance_cache(*, seed_l6: bool = True) -> dict[str, Any]:
    """Atualiza manifests L6, Prove externo e cache para /finance."""
    from learning_agent.core import agent_capability, finance_economic_news, finance_training_extensions

    if seed_l6:
        finance_training_extensions.run_diversified_data_fetch(source="fixture")
        finance_training_extensions.ensure_microeconomics_indexed(sync_cloud=False)
        finance_economic_news.fetch_and_index_economic_news(use_web_fallback=False)
        finance_training_extensions.run_cross_validation_check()

    cap = agent_capability.compute_agent_capability(AGENT)
    status = build_finance_status(fast=False)
    status["capability_level"] = cap.get("level")
    status["capability_score"] = cap.get("score")
    status["level"] = cap.get("level")
    status["score"] = cap.get("score")
    status["finance_l6_specialist"] = (cap.get("level_6") or {}).get("finance_l6_specialist")
    status["l6_operational"] = (cap.get("level_6") or {}).get("operational_checklist") or {}
    if cap.get("next_actions"):
        status["suggested_actions"] = cap.get("next_actions")
    status["l6_extensions"] = [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "passed": c.get("passed"),
        }
        for c in (status.get("criteria_ok") or []) + (status.get("criteria_fail") or [])
        if str(c.get("id", "")).startswith("F") and c.get("id") in {"F6", "F7", "F8", "F9"}
    ]

    last = _read_json(LAST) or {}
    last.update(
        {
            "curriculum_level": status.get("curriculum_current") or last.get("curriculum_level"),
            "target_level": status.get("curriculum_target") or last.get("target_level"),
            "capability_level": cap.get("level"),
            "capability_score": cap.get("score"),
            "parity_score": last.get("parity_score") or (cap.get("level_6") or {}).get("composite_score"),
            "blind_score": status.get("blind_score"),
        }
    )
    LAST.parent.mkdir(parents=True, exist_ok=True)
    LAST.write_text(json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_status_cache(status, cap)
    return status


def build_finance_status(*, fast: bool = False) -> dict[str, Any]:
    from learning_agent.core import agent_capability, agent_curriculum

    if fast:
        cached = _load_status_cache()
        if cached:
            return cached

    last = _read_json(LAST) or {}
    external = _external_assessment(use_cache=fast)
    if fast:
        cap = {
            "level": last.get("capability_level") or last.get("curriculum_level"),
            "score": last.get("capability_score"),
        }
        milestone = {
            "current_level": last.get("curriculum_level"),
            "target_level": last.get("target_level"),
            "milestone": {"title": last.get("milestone_title", "")},
            "suggested_actions": [],
        }
    else:
        cap = agent_capability.compute_agent_capability(AGENT)
        milestone = agent_curriculum.get_next_milestone(AGENT)
    passed = external.get("passed_count")
    total = external.get("total", 9)
    training = {
        "agent": AGENT,
        "quality_mode": True,
        "capability_level": cap.get("level"),
        "capability_score": cap.get("score") if cap.get("score") is not None else "?",
        "external_ready": external.get("external_ready", False),
        "external_pass": f"{passed}/{total}" if passed is not None else f"?/{total}",
        "curriculum_current": last.get("curriculum_level") or milestone.get("current_level"),
        "curriculum_target": last.get("target_level") or milestone.get("target_level"),
        "milestone_title": (milestone.get("milestone") or {}).get("title"),
        "suggested_actions": milestone.get("suggested_actions", []),
        "last_cycle": last.get("cycle"),
        "last_dimension": last.get("dimension"),
        "parity_score": last.get("parity_score"),
        "motor": "Raven + Cursor + web + L6 (micro, dados, news, cross-val) + pratica",
    }
    blind_score = last.get("blind_score", 0) if fast else None
    result = _status_from_parts(training, external, blind_score=blind_score)
    if not fast:
        result["finance_l6_specialist"] = (cap.get("level_6") or {}).get("finance_l6_specialist")
        result["l6_operational"] = (cap.get("level_6") or {}).get("operational_checklist") or {}
        if cap.get("next_actions"):
            result["suggested_actions"] = cap.get("next_actions")
        result["l6_extensions"] = [
            {"id": c.get("id"), "title": c.get("title"), "passed": c.get("passed")}
            for c in (result.get("criteria_ok") or []) + (result.get("criteria_fail") or [])
            if c.get("id") in {"F6", "F7", "F8", "F9"}
        ]
    return result


def format_finance_telegram_message(
    status: dict[str, Any] | None = None,
    *,
    fast: bool = True,
) -> str:
    s = status or build_finance_status(fast=fast)
    go = "Go" if s.get("external_ready") else "No-Go"
    running = "rodando" if s.get("running") else "parado"

    lines = [
        f"Finance-lead — {running}",
        f"Prove externo: {s.get('external_pass')} ({go})",
        f"Blind score: {s.get('blind_score', 0)}%",
        f"Nivel interno: L{s.get('level')} ({s.get('score')}/100)",
    ]

    if s.get("end_at"):
        lines.append(f"Parada prevista: {s['end_at']}")

    if s.get("target_level") or s.get("curriculum_target"):
        cl = s.get("curriculum_level") or s.get("curriculum_current", "?")
        tl = s.get("target_level") or s.get("curriculum_target", "?")
        mt = s.get("milestone_title", "")
        lines.append(f"Curriculo: L{cl} -> L{tl} {mt}".strip())

    if s.get("last_cycle"):
        qual = []
        if s.get("teacher_distilled"):
            qual.append("teacher OK")
        if s.get("study_distilled"):
            qual.append("estudo destilado")
        qual_txt = ", ".join(qual) if qual else "ciclo em progresso"
        lines.append(
            f"Ultimo ciclo #{s['last_cycle']} ({s.get('last_dimension', '?')}) — {qual_txt}"
        )
        if s.get("last_topic"):
            lines.append(f"Topico: {s['last_topic']}")
        if s.get("pairs_after"):
            lines.append(f"Pares destilacao: {s['pairs_after']} | HF: {s.get('training_examples', '?')} ex.")

    if s.get("readiness_pct") is not None:
        lines.append(f"Readiness Raven: {s['readiness_pct']}%")

    l6_ext = s.get("l6_extensions") or [
        c
        for c in (s.get("criteria_ok") or []) + (s.get("criteria_fail") or [])
        if c.get("id") in {"F6", "F7", "F8", "F9"}
    ]
    if l6_ext:
        ok = sum(1 for c in l6_ext if c.get("passed"))
        lines.append(f"Extensoes L6: {ok}/{len(l6_ext)} OK")
        if s.get("finance_l6_specialist"):
            lines.append("Trilha: Especialista L6 ativa")

    fails = s.get("criteria_fail") or []
    l6_op = s.get("l6_operational") or {}
    if l6_op.get("missing"):
        lines.append("Checklist L6 operacional:")
        for key in l6_op["missing"][:4]:
            chk = (l6_op.get("checks") or {}).get(key, {})
            lines.append(f"  - {key}: {chk.get('detail', '')}")
    elif fails:
        lines.append("Criterios pendentes:")
        for c in fails[:3]:
            lines.append(f"  - {c.get('id')}: {c.get('title')}")

    lines.append("")
    lines.append("Foco: QUALIDADE > quantidade (Prove externo manda, nao volume de ciclos).")
    return "\n".join(lines)


def finance_context_for_chat() -> str:
    """Bloco injetado no chat Telegram quando perguntam sobre finance-lead."""
    from learning_agent.core import finance_training_directives

    s = build_finance_status()
    return (
        "DADOS ATUAIS FINANCE-LEAD (use na resposta, seja concisa):\n"
        + format_finance_telegram_message(s)
        + "\n"
        + finance_training_directives.chat_rules_block()
    )


def is_finance_status_query(text: str) -> bool:
    t = text.lower()
    if t.startswith("/finance"):
        return True
    keys = (
        "finance-lead",
        "finance lead",
        "financelead",
        "treinamento finance",
        "melhorar o finance",
        "melhorar treino",
        "sugest",
        "aplicar treino",
        "andamento finance",
        "como está o finance",
        "como esta o finance",
        "nivel do finance",
        "nível do finance",
        "prove finance",
        "blind finance",
        "investimento pf",
    )
    return any(k in t for k in keys)
