"""Mentoria fixa — par sênior → aprendiz por arquétipo."""

from __future__ import annotations

import uuid
from typing import Any

from learning_agent.core import agent_collaboration, knowledge, llm as llm_core

MENTOR_PAIRS: list[tuple[str, str]] = [
    ("backend-lead", "reliability-lead"),
    ("frontend-lead", "qa-guardian"),
    ("data-engineer", "backend-lead"),
    ("qa-guardian", "frontend-lead"),
    ("reliability-lead", "data-engineer"),
]


def _manifest(agent: str) -> dict[str, Any]:
    return agent_collaboration._load_manifest(agent) or {}


def _llm(system: str, user: str, *, max_tokens: int = 300) -> str:
    try:
        reply, _ = llm_core.chat_with_fallback(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.5,
        )
        return reply
    except Exception:
        return "(mentoria — modelo indisponível)"


def run_mentor_session(
    mentor: str | None = None,
    mentee: str | None = None,
    *,
    broadcast_observer: bool = True,
) -> dict[str, Any]:
    """Sessão de mentoria: mentor avalia lacunas do aprendiz e prescreve prática."""
    pair = MENTOR_PAIRS[0]
    men = mentor or pair[0]
    tee = mentee or pair[1]
    mm, tm = _manifest(men), _manifest(tee)

    from learning_agent.core import agent_capability

    cap = agent_capability.compute_agent_capability(tee)
    missing = cap.get("level_5", {}).get("missing", [])
    gaps = agent_collaboration.detect_knowledge_gaps(tee)

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(
            men, f"Mentoria para {tee}: nível {cap.get('level')}", level="mentor-start"
        )

    lesson = _llm(
        f"Você é {mm.get('display_name', men)}, mentor sênior. "
        "Em 5-7 frases, ensine o aprendiz com exercício prático concreto.",
        f"Aprendiz: {tee} (nível {cap.get('level')}). "
        f"Lacunas L5: {missing}. Gaps: {[g.get('topic') for g in gaps.get('gaps', [])[:3]]}",
    )

    reflection = _llm(
        f"Você é {tm.get('display_name', tee)}. Em 3 frases: o que entendeu e o que vai praticar.",
        lesson,
        max_tokens=180,
    )

    agent_collaboration.share_insight(men, lesson, f"mentoria→{tee}", to_agents=[tee, "all"])
    agent_collaboration.share_insight(tee, reflection, "mentoria-reflexão", to_agents=[men, "all"])

    knowledge.add_note(
        f"[Mentoria] {men} → {tee}",
        f"## Lição\n{lesson}\n\n## Reflexão aprendiz\n{reflection}",
        tags=["mentoring", f"agent:{men}", f"agent:{tee}"],
    )

    if broadcast_observer:
        agent_collaboration._broadcast_to_observer(tee, reflection[:200], level="mentor-reflection")

    return {
        "success": True,
        "action": "mentor_session",
        "thread_id": f"mentor-{uuid.uuid4().hex[:10]}",
        "mentor": men,
        "mentee": tee,
        "lesson": lesson,
        "reflection": reflection,
        "mentee_level": cap.get("level"),
    }
