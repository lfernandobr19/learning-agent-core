"""Contexto agregado para tarefas — um pacote pronto antes de implementar."""

from __future__ import annotations

from typing import Any

from learning_agent.core import active_learning, codebase, curriculum, errors, graph, knowledge, progress, sessions


def get_context_for_task(task: str, limit: int = 5) -> dict[str, Any]:
    prog = progress.get_progress()
    next_topic = curriculum.get_next_topic()

    return {
        "task": task,
        "knowledge": knowledge.search(task, limit=limit),
        "code": codebase.search_code(task, limit=limit),
        "sessions": sessions.recall_sessions(task, limit=3),
        "past_errors": errors.get_related_errors(task, limit=3),
        "weak_areas": prog.get("weak_areas", [])[:5],
        "recent_notes": [
            {"title": n["title"], "tags": n.get("tags", [])}
            for n in prog.get("recent_notes", [])[:5]
        ],
        "curriculum_next": next_topic.get("next_topic") if next_topic.get("found") else None,
        "concept_graph": graph.get_related_concepts(task.split()[0] if task else "python", depth=1, limit=10),
        "learning_suggestions": active_learning.suggest_learning(3).get("suggestions", []),
        "hints": _build_hints(task, prog),
    }


def _build_hints(task: str, prog: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    weak = prog.get("weak_areas", [])
    if weak:
        hints.append(f"Lacunas em quiz: {', '.join(weak[:3])}")
    if prog.get("due_quizzes"):
        hints.append(f"{len(prog['due_quizzes'])} revisões de quiz pendentes")
    hints.append("Use search_code + search_knowledge antes de implementar")
    hints.append("Registre falhas com record_failure quando verified=false")
    return hints
