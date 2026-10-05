"""Supervisor Cursor → Ravenna: encaminha, avalia, corrige, consolida."""

from __future__ import annotations

import re
from typing import Any

from learning_agent.core import chat

THEATER_PATTERNS = (
    r"vou estudar",
    r"volto em instantes",
    r"deixa eu analisar",
    r"em seguida retorno",
    r"aguarde que",
    r"preparando resposta",
)

ACTION_VERBS = (
    "implement",
    "implemente",
    "crie",
    "criar",
    "corrija",
    "fix",
    "rode",
    "execute",
    "faça",
    "faca",
    "configure",
    "instale",
)


def evaluate_ravenna_reply(
    user_message: str,
    ravenna_result: dict[str, Any],
) -> dict[str, Any]:
    """Heurística leve — score 0–100 e flags de correção."""
    issues: list[str] = []
    score = 100

    if not ravenna_result.get("success"):
        issues.append(f"erro_llm: {ravenna_result.get('error', '?')[:120]}")
        score = 0
        return {"score": score, "issues": issues, "needs_correction": True}

    reply = (ravenna_result.get("reply") or "").strip()
    if len(reply) < 20:
        issues.append("resposta_vazia_ou_curta")
        score -= 40

    lower = reply.lower()
    for pat in THEATER_PATTERNS:
        if re.search(pat, lower):
            issues.append(f"teatro: {pat}")
            score -= 35
            break

    user_lower = user_message.lower()
    wants_action = any(v in user_lower for v in ACTION_VERBS)
    has_write = "```write" in reply or "```shell" in reply
    if wants_action and not has_write and "modo agent" not in lower:
        if not any(w in lower for w in ("implementei", "criei", "alterei", "arquivo", "commit")):
            issues.append("pedido_acao_sem_entrega")
            score -= 25

    needs = score < 70 or bool(issues)
    return {
        "score": max(0, score),
        "issues": issues,
        "needs_correction": needs,
    }


def orchestrate(
    message: str,
    *,
    delegate_agent: str | None = None,
    editor_context: str = "",
    task_mode: str = "chat",
    retry_on_fail: bool = True,
) -> dict[str, Any]:
    """Encaminha à Ravenna, avalia e opcionalmente re-prompta."""
    extra = (
        "Responda como Ravenna com entrega concreta. "
        "Proibido teatro ('vou estudar e volto'). "
        "Se for tarefa de código, use blocos write/shell ou diga bloqueio técnico real."
    )

    result = chat.reply(
        message,
        channel="ide",
        user_id="orchestrator-supervisor",
        include_context=bool(editor_context.strip()),
        delegate_agent=delegate_agent,
        extra_system=extra,
        editor_context=editor_context,
        task_mode=task_mode,
        persist_history=False,
    )

    evaluation = evaluate_ravenna_reply(message, result)

    if retry_on_fail and evaluation["needs_correction"]:
        fix_prompt = (
            f"Corrija sua resposta anterior. Problemas: {', '.join(evaluation['issues'])}. "
            f"Pedido original: {message[:500]}"
        )
        retry = chat.reply(
            fix_prompt,
            channel="ide",
            user_id="orchestrator-supervisor-retry",
            delegate_agent=delegate_agent,
            extra_system=extra,
            editor_context=editor_context,
            task_mode=task_mode,
            persist_history=False,
        )
        retry_eval = evaluate_ravenna_reply(message, retry)
        if retry_eval["score"] >= evaluation["score"]:
            result = retry
            evaluation = retry_eval

    return {
        "success": result.get("success", False),
        "reply": result.get("reply"),
        "model": result.get("model"),
        "agent": result.get("agent", "Ravenna"),
        "delegate_agent": result.get("delegate_agent"),
        "evaluation": evaluation,
        "ravenna_raw": result,
    }
