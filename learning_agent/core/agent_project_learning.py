"""Aprendizado por projeto — memória enxuta, reutilizável e autodidata (gemma4-raven)."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import DATA_DIR
from learning_agent.core import errors, knowledge

PROJECT_LEARNING_DIR = DATA_DIR / "project-learning"
MAX_JOURNAL_ENTRIES = 48
MIN_UTILITY_TO_RECORD = 0.28
MIN_UTILITY_TO_GLOBAL = 0.5

_GENERIC_NOISE = (
    "autonomia não passou",
    "falha não classificada",
    "revisar write/patch",
    "falha ao chamar o modelo",
)
_ACTION_KEYWORDS = (
    "pytest",
    "import",
    "workspace",
    "patch",
    "syntax",
    "mount",
    "docker",
    "fastapi",
    "home assistant",
    "tailwind",
    "typescript",
)


def _journal_path(project_id: str) -> Path:
    safe = project_id.replace("\\", "/").strip("/").replace("/", "_") or "default"
    return PROJECT_LEARNING_DIR / f"{safe}.jsonl"


def _fingerprint(error: str, phase: str = "") -> str:
    norm = re.sub(r"\s+", " ", (error or "").lower().strip())[:600]
    raw = f"{phase.strip().lower()}:{norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _utility_score(*, error: str, fix: str, phase: str) -> float:
    err = (error or "").strip()
    fix_text = (fix or "").strip()
    score = 0.2 if len(err) >= 24 else 0.05
    if fix_text and len(fix_text) >= 28 and "FALHAS CRÍTICAS" not in fix_text:
        score += 0.38
    if phase and phase not in ("autonomy", "geral", ""):
        score += 0.12
    low = err.lower()
    if any(k in low for k in _ACTION_KEYWORDS):
        score += 0.18
    if any(g in low for g in _GENERIC_NOISE) and len(fix_text) < 40:
        score -= 0.35
    if fix_text and fix_text.lower().startswith("add readme"):
        score += 0.08
    return max(0.0, min(1.0, score))


def _load_all_lessons(project_id: str) -> list[dict[str, Any]]:
    path = _journal_path(project_id)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _write_lessons(project_id: str, rows: list[dict[str, Any]]) -> None:
    PROJECT_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    path = _journal_path(project_id)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _compact_journal(project_id: str) -> None:
    rows = _load_all_lessons(project_id)
    if len(rows) <= MAX_JOURNAL_ENTRIES:
        return
    ranked = sorted(
        rows,
        key=lambda r: (
            float(r.get("utility") or 0),
            int(r.get("occurrence_count") or 1),
            r.get("at") or "",
        ),
        reverse=True,
    )
    keep = {r.get("fingerprint") for r in ranked[:MAX_JOURNAL_ENTRIES]}
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in ranked:
        fp = str(row.get("fingerprint") or "")
        if fp in seen or fp not in keep:
            continue
        seen.add(fp)
        kept.append(row)
    kept.sort(key=lambda r: r.get("at") or "")
    _write_lessons(project_id, kept[-MAX_JOURNAL_ENTRIES:])


def _find_by_fingerprint(project_id: str, fp: str) -> dict[str, Any] | None:
    for row in reversed(_load_all_lessons(project_id)):
        if row.get("fingerprint") == fp:
            return row
    return None


def record_lesson(
    project_id: str,
    *,
    error: str,
    fix: str = "",
    phase: str = "",
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    kind: str = "failure",
    force: bool = False,
) -> dict[str, Any]:
    """Persiste só lições úteis e reutilizáveis."""
    err = (error or "").strip()
    fix_text = (fix or "").strip()
    utility = _utility_score(error=err, fix=fix_text, phase=phase)
    fp = _fingerprint(err, phase)

    if not force and utility < MIN_UTILITY_TO_RECORD:
        return {
            "success": False,
            "skipped": True,
            "reason": "utility_below_threshold",
            "utility": utility,
            "fingerprint": fp,
        }

    existing = _find_by_fingerprint(project_id, fp)
    if existing and not force:
        existing["occurrence_count"] = int(existing.get("occurrence_count") or 1) + 1
        existing["last_seen"] = datetime.now(timezone.utc).isoformat()
        if fix_text and len(fix_text) > len(str(existing.get("fix") or "")):
            existing["fix"] = fix_text[:4000]
            existing["utility"] = max(float(existing.get("utility") or 0), utility)
        rows = _load_all_lessons(project_id)
        updated = [
            existing if r.get("fingerprint") == fp else r for r in rows
        ]
        _write_lessons(project_id, updated)
        return {"success": True, "lesson": existing, "duplicate_bumped": True}

    row: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "phase": phase,
        "kind": kind,
        "error": err[:4000],
        "fix": fix_text[:4000],
        "tags": tags or [project_id, "gemma4-raven"],
        "meta": meta or {},
        "fingerprint": fp,
        "utility": round(utility, 3),
        "occurrence_count": 1,
    }
    PROJECT_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    with _journal_path(project_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    global_error = None
    if utility >= MIN_UTILITY_TO_GLOBAL and fix_text:
        ctx = f"[{project_id}] {phase}".strip()
        global_error = errors.record_failure(ctx, row["error"], row["fix"], tags=row["tags"])

    _compact_journal(project_id)
    if kind != "compound":
        synthesize_compound_lessons(project_id, persist=True)
    return {"success": True, "lesson": row, "global_error": global_error, "utility": utility}


def list_lessons(
    project_id: str,
    *,
    limit: int = 12,
    min_utility: float = 0.0,
    kinds: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows = _load_all_lessons(project_id)
    allowed = set(kinds) if kinds else None
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if float(row.get("utility") or 0) < min_utility:
            continue
        if allowed and row.get("kind") not in allowed:
            continue
        filtered.append(row)
    filtered.sort(
        key=lambda r: (
            float(r.get("utility") or 0),
            int(r.get("occurrence_count") or 1),
            r.get("at") or "",
        ),
        reverse=True,
    )
    return list(reversed(filtered[-limit:]))


def mark_lesson_reused(project_id: str, fingerprint: str) -> None:
    rows = _load_all_lessons(project_id)
    changed = False
    for row in rows:
        if row.get("fingerprint") == fingerprint:
            row["reuse_count"] = int(row.get("reuse_count") or 0) + 1
            row["last_reused"] = datetime.now(timezone.utc).isoformat()
            changed = True
    if changed:
        _write_lessons(project_id, rows)


def synthesize_compound_lessons(project_id: str, *, persist: bool = True) -> list[dict[str, Any]]:
    """Deriva regras compostas a partir de lições existentes (autodidata)."""
    base = [r for r in _load_all_lessons(project_id) if r.get("kind") != "compound"]
    if len(base) < 2:
        return []

    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in base:
        err = str(row.get("error") or "").lower()
        for kw in _ACTION_KEYWORDS:
            if kw in err:
                buckets.setdefault(kw, []).append(row)

    compounds: list[dict[str, Any]] = []
    for kw, group in buckets.items():
        if len(group) < 2:
            continue
        fixes = [str(g.get("fix") or "").strip() for g in group if g.get("fix")]
        phases = sorted({str(g.get("phase") or "") for g in group if g.get("phase")})
        phase_text = f" (fases: {', '.join(phases[:3])})" if phases else ""
        insight = (
            f"Padrão recorrente «{kw}» em {len(group)} falhas{phase_text}. "
            "Antes de repetir a tarefa, aplique as correções já registradas e valide o ambiente."
        )
        if fixes:
            insight += f" Correções vistas: {'; '.join(fixes[:2])[:280]}."
        fp = _fingerprint(insight, f"compound:{kw}")
        if _find_by_fingerprint(project_id, fp):
            continue
        compounds.append(
            {
                "kind": "compound",
                "error": insight,
                "fix": "Consulte get_project_lessons e search_knowledge antes de implementar.",
                "phase": "síntese",
                "utility": min(0.95, 0.55 + 0.08 * len(group)),
                "fingerprint": fp,
                "source_keywords": [kw],
                "source_count": len(group),
            }
        )

    if persist and compounds:
        PROJECT_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        path = _journal_path(project_id)
        with path.open("a", encoding="utf-8") as fh:
            for comp in compounds:
                row = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "project_id": project_id,
                    "phase": comp["phase"],
                    "kind": "compound",
                    "error": comp["error"],
                    "fix": comp["fix"],
                    "tags": [project_id, "gemma4-raven", "compound"],
                    "meta": {"source_keywords": comp.get("source_keywords")},
                    "fingerprint": comp["fingerprint"],
                    "utility": comp["utility"],
                    "occurrence_count": 1,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        _compact_journal(project_id)
    return compounds


def expand_knowledge_from_lessons(project_id: str, topic: str, *, limit: int = 5) -> dict[str, Any]:
    """Liga o que já aprendeu no projeto com novo tópico (flexibilidade autodidata)."""
    topic_low = (topic or "").strip().lower()
    related = []
    for row in list_lessons(project_id, limit=24, min_utility=0.3):
        blob = f"{row.get('error', '')} {row.get('fix', '')}".lower()
        if topic_low and topic_low in blob:
            related.append(row)
        elif not topic_low:
            related.append(row)
    rag_hits = knowledge.search(f"{topic} {project_id}", limit=limit) if topic_low else []

    bridges: list[str] = []
    for row in related[:4]:
        kw = str(row.get("phase") or row.get("kind") or "lição")
        bridges.append(f"- [{kw}] {str(row.get('error') or '')[:180]}")
    if rag_hits:
        bridges.append("- Conhecimento indexado relacionado:")
        for hit in rag_hits[:3]:
            meta = hit.get("metadata") or {}
            bridges.append(f"  • {meta.get('title') or hit.get('id')}: {(hit.get('content') or '')[:120]}")

    return {
        "project_id": project_id,
        "topic": topic,
        "related_lessons": related[:6],
        "knowledge_hits": rag_hits,
        "bridges": bridges,
        "hint": "Use research_trusted_sources se knowledge_hits for escasso.",
    }


def format_lessons_block(project_id: str, *, limit: int = 6) -> str:
    lessons = list_lessons(project_id, limit=limit, min_utility=0.32)
    compounds = [r for r in lessons if r.get("kind") == "compound"]
    failures = [r for r in lessons if r.get("kind") != "compound"]
    if not lessons:
        return ""

    lines = [
        f"MEMÓRIA DO PROJETO `{project_id}` — só o essencial reutilizável (não repita):"
    ]
    if compounds:
        lines.append("Regras compostas (aprendidas das suas falhas):")
        for i, lesson in enumerate(compounds[:3], 1):
            lines.append(f"  C{i}. {str(lesson.get('error') or '')[:420]}")
    for i, lesson in enumerate(failures[-limit:], 1):
        phase = lesson.get("phase") or "geral"
        err = str(lesson.get("error") or "")[:380]
        fix = str(lesson.get("fix") or "")[:300]
        util = lesson.get("utility")
        lines.append(f"{i}. [{phase}] (u={util}) {err}")
        if fix:
            lines.append(f"   → {fix}")
    lines.append(
        "Tools: get_project_lessons | record_project_lesson (só falhas novas e acionáveis) | "
        "expand_project_knowledge | research_trusted_sources | consult_specialist"
    )
    return "\n".join(lines)


def record_from_autonomy(
    project_id: str,
    *,
    message: str,
    autonomy: dict[str, Any] | None,
    phase: str = "",
) -> dict[str, Any] | None:
    """Extrai falhas acionáveis de um ciclo de autonomia."""
    if not autonomy or autonomy.get("passed"):
        return None
    attempts = autonomy.get("attempts") or []
    last = attempts[-1] if attempts else {}
    validation = last.get("validation") or {}
    checklist = last.get("checklist") or {}
    critique = last.get("critique") or {}
    failure_parts: list[str] = []
    for bucket in (validation.get("failures"), checklist.get("failures"), critique.get("failures")):
        if isinstance(bucket, list):
            failure_parts.extend(str(x) for x in bucket if x)
    applied = last.get("applied") or {}
    if applied.get("error"):
        failure_parts.append(str(applied["error"]))
    if not failure_parts:
        return None
    error_text = "\n".join(dict.fromkeys(failure_parts[:8]))
    fix_hint = str(critique.get("repairPrompt") or "")[:800]
    if "FALHAS CRÍTICAS" in fix_hint:
        fix_hint = ""
    return record_lesson(
        project_id,
        error=error_text,
        fix=fix_hint,
        phase=phase or str(last.get("phase") or "autonomy"),
        meta={"message_preview": (message or "")[:200]},
    )


def project_id_from_root(project_root: str | None) -> str:
    root = (project_root or "").replace("\\", "/").strip("/")
    return root.split("/")[-1] if root else "default"


def research_trusted_sources(
    query: str,
    *,
    limit: int = 3,
    index: bool = True,
    project_id: str = "",
) -> dict[str, Any]:
    """Pesquisa fontes confiáveis e opcionalmente indexa no conhecimento."""
    from learning_agent.core import web

    hits = web.search_trusted_web(query, limit=limit)
    learned: list[dict[str, Any]] = []
    errors_out: list[str] = []
    tags = ["trusted-web", "gemma4-raven"]
    if project_id:
        tags.append(project_id)

    if index:
        for item in hits:
            url = (item.get("url") or "").strip()
            if not url:
                continue
            try:
                entry = web.fetch_and_learn(
                    url,
                    title=item.get("title", ""),
                    tags=tags,
                    auto_sync=False,
                )
                entry["snippet"] = item.get("snippet", "")
                learned.append(entry)
            except Exception as exc:
                errors_out.append(f"{url}: {exc}")

    return {
        "success": bool(hits),
        "query": query,
        "sources": hits,
        "indexed": learned,
        "errors": errors_out,
        "hint": "Use expand_project_knowledge para ligar com lições do projeto.",
    }


def consult_specialist(
    specialist: str,
    topic: str,
    *,
    project_id: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Consulta insights de outro agente especialista e conhecimento relacionado."""
    from learning_agent.core import agent_collaboration

    slug = specialist.strip().lower().replace("_", "-")
    peers = agent_collaboration.get_peer_insights(slug, limit=limit)
    gaps = agent_collaboration.detect_knowledge_gaps(slug, extra_topics=[topic] if topic else None)
    local = knowledge.search(f"{topic} {slug}", limit=limit) if topic else []

    project_bridge = None
    if project_id:
        project_bridge = expand_knowledge_from_lessons(project_id, topic, limit=3)

    insights = peers.get("insights") or []
    topic_low = (topic or "").lower()
    filtered = [
        i
        for i in insights
        if not topic_low
        or topic_low in str(i.get("topic", "")).lower()
        or topic_low in str(i.get("content", "")).lower()
    ]
    if topic_low and not filtered:
        filtered = insights[:3]

    takeaways: list[str] = []
    for item in filtered[:3]:
        takeaways.append(f"• {item.get('from_agent')}: {str(item.get('content') or '')[:220]}")
    for hit in (peers.get("knowledge_hits") or [])[:2]:
        takeaways.append(f"• KB: {(hit.get('content') or '')[:180]}")

    return {
        "success": True,
        "specialist": slug,
        "topic": topic,
        "takeaways": takeaways,
        "peer_insights": filtered,
        "knowledge_hits": local,
        "gaps": (gaps.get("gaps") or [])[:3],
        "project_bridge": project_bridge,
        "hint": "Absorva takeaways com record_project_lesson (kind=insight) se for reutilizável.",
    }
