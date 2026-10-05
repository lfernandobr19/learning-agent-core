"""Painel de supervisão — todos os agentes direcionam a Ravenna em cada processo."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

BroadcastFn = Callable[..., Awaitable[None]]
PauseFn = Callable[[float], Awaitable[None]]

# Papéis que supervisionam a Ravenna (não inclui ravenna nem system genérico)
SUPERVISOR_ROSTER: list[dict[str, str]] = [
    {
        "role": "cursor",
        "label": "Cursor",
        "focus": "Coordena execução, prioriza diff mínimo e provas reais.",
    },
    {
        "role": "architect",
        "label": "Arquiteta de Sistemas",
        "focus": "Camadas, contratos, desacoplamento e decisões estruturais.",
    },
    {
        "role": "senior-fe",
        "label": "Eng. Frontend Sênior",
        "focus": "React, a11y, performance, testes UI e experiência RemoteApp.",
    },
    {
        "role": "senior-be",
        "label": "Eng. Backend Sênior",
        "focus": "FastAPI async, validação, WS/REST e resiliência.",
    },
    {
        "role": "reviewer",
        "label": "Revisor Sênior",
        "focus": "Segurança, regressões, gaps vs patamar staff.",
    },
    {
        "role": "mentor",
        "label": "Mentor de Qualidade",
        "focus": "Diretivas explícitas para a Ravenna e próximo patamar.",
    },
    {
        "role": "quiz-master",
        "label": "Quiz Master",
        "focus": "Consolidação via quizzes e spaced repetition.",
    },
]


@dataclass
class SupervisionContext:
    """Contexto de uma rodada de supervisão."""

    level: str
    topic: str
    process: str  # theater | qa | consolidation | session
    lesson: str = ""
    superior: str = ""
    phase: str = ""
    staff_brief: str = ""
    mentor_directive: str = ""
    reviewer_focus: str = ""
    track_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _architect_message(ctx: SupervisionContext) -> str:
    if ctx.process == "qa":
        return (
            f"**Arquiteta — {ctx.topic}**\n"
            f"{ctx.staff_brief or 'Valido contratos entre camadas nesta fase.'}\n"
            "Ravenna: trace UI → API → core antes de considerar a fase concluída."
        )
    if ctx.lesson:
        return (
            f"**Arquiteta — {ctx.level}**\n"
            f"Lição principal absorvida; vigio camadas e contratos.\n"
            f"Patamar superior: {ctx.superior or 'services testáveis e DTOs explícitos.'}"
        )
    return (
        f"**Arquiteta — {ctx.level}**\n"
        "Ravenna: mantenha api → core → db sem lógica de negócio vazando para handlers."
    )


def _senior_fe_message(ctx: SupervisionContext) -> str:
    if ctx.process == "qa" and ctx.track_id in ("vitest-frontend", "playwright-e2e", "playwright-ui"):
        return (
            f"**Frontend — {ctx.topic}**\n"
            "Ravenna: teste DOM e fluxos visíveis; Three.js/WebGL não entram no jsdom.\n"
            "Confirme shell RemoteApp, chat e painéis após cada verde."
        )
    if ctx.track_id in ("frontend-excellence",) or "front" in ctx.topic.lower():
        return (
            f"**Frontend — {ctx.level}**\n"
            f"{ctx.lesson[:280] + '…' if len(ctx.lesson) > 280 else ctx.lesson or 'Componentes pequenos, a11y e performance.'}"
        )
    return (
        f"**Frontend — {ctx.level}**\n"
        "Ravenna: cada entrega na IDE deve manter o tema RemoteApp vivo sem quebrar a11y nem layout."
    )


def _senior_be_message(ctx: SupervisionContext) -> str:
    if ctx.process == "qa":
        be_suites = {"pytest-workspace", "pytest-attachments", "pytest-terminal", "pytest-mcp", "pytest-git", "run-proofs"}
        if ctx.track_id in be_suites:
            return (
                f"**Backend — {ctx.topic}**\n"
                f"{ctx.staff_brief[:200] + '…' if len(ctx.staff_brief) > 200 else ctx.staff_brief or 'Contrato HTTP/WS sólido.'}\n"
                "Ravenna: reinicie a API após novas rotas antes de celebrar e2e."
            )
    if ctx.track_id in ("backend-excellence", "security", "observability", "scalability"):
        return (
            f"**Backend — {ctx.level}**\n"
            f"{ctx.lesson[:280] + '…' if len(ctx.lesson) > 280 else ctx.lesson or 'Handlers finos, timeouts no LLM.'}"
        )
    return (
        f"**Backend — {ctx.level}**\n"
        "Ravenna: valide Pydantic, async e subprocess seguro em toda rota nova."
    )


def _reviewer_message(ctx: SupervisionContext) -> str:
    if ctx.reviewer_focus:
        return f"**Revisor — {ctx.topic}**\n{ctx.reviewer_focus}"
    if ctx.superior:
        return (
            f"**Revisor — {ctx.level}**\n"
            f"Gap: MVP ok, patamar **{ctx.level}** ainda incompleto.\n"
            f"Priorize: {ctx.superior}"
        )
    return (
        f"**Revisor — {ctx.level}**\n"
        "Ravenna: nenhum verde mascarando regressão de segurança ou contrato quebrado."
    )


def _mentor_message(ctx: SupervisionContext) -> str:
    if ctx.mentor_directive:
        return f"**Mentor → Ravenna**\n{ctx.mentor_directive}"
    return (
        f"**Mentor → Ravenna**\n"
        f"Processo **{ctx.process}** · {ctx.topic}: internalize, registre nota e aplique no próximo diff."
    )


def _cursor_message(ctx: SupervisionContext) -> str:
    return (
        f"**Cursor — supervisão ativa**\n"
        f"Processo: `{ctx.process}` · {ctx.level} · {ctx.topic}.\n"
        "Todos os agentes direcionam a Ravenna; ela executa com diff mínimo e provas reais."
    )


def _quiz_master_message(ctx: SupervisionContext) -> str:
    if ctx.process == "consolidation":
        qcount = ctx.extra.get("quiz_count", 0)
        return (
            f"**Quiz Master → Ravenna**\n"
            f"Consolidação gerou {qcount} desafios — responda via chat ou subagente quiz-master.\n"
            "Áreas fracas viram reforço antes de features novas."
        )
    if ctx.process == "qa":
        return (
            "**Quiz Master → Ravenna**\n"
            "Após bateria QA, crie ou revise quizzes de IDE/testing se algo falhou.\n"
            "Verde sem lição registrada não conta no spaced repetition."
        )
    return (
        f"**Quiz Master → Ravenna**\n"
        f"Tópico **{ctx.topic}**: ao fechar o ciclo, confirme `due_quizzes` e `get_progress`."
    )


_BUILDERS: dict[str, Callable[[SupervisionContext], str]] = {
    "cursor": _cursor_message,
    "architect": _architect_message,
    "senior-fe": _senior_fe_message,
    "senior-be": _senior_be_message,
    "reviewer": _reviewer_message,
    "mentor": _mentor_message,
    "quiz-master": _quiz_master_message,
}


def supervision_messages(ctx: SupervisionContext) -> list[tuple[str, str, str]]:
    """Lista (role, label, content) para cada agente supervisor."""
    out: list[tuple[str, str, str]] = []
    for agent in SUPERVISOR_ROSTER:
        role = agent["role"]
        label = agent["label"]
        builder = _BUILDERS.get(role)
        content = builder(ctx) if builder else f"**{label}** — supervisionando {ctx.topic}."
        out.append((role, label, content))
    return out


async def broadcast_supervision_round(
    ctx: SupervisionContext,
    *,
    broadcast: BroadcastFn | None = None,
    pause_fn: PauseFn | None = None,
    pause_seconds: float = 0.35,
    skip_roles: set[str] | None = None,
) -> None:
    """Todos os agentes falam no observador antes da Ravenna refletir."""
    if broadcast is None:
        from learning_agent.core import theater

        async def _default_broadcast(role: str, agent: str, content: str, *, level: str = "") -> None:
            await theater.post_agent_message(role, agent, content, level=level)

        broadcast = _default_broadcast

    if pause_fn is None:
        from learning_agent.core import theater

        pause_fn = theater._pause

    skip = skip_roles or set()
    for role, label, content in supervision_messages(ctx):
        if role in skip:
            continue
        await broadcast(role, label, content, level=ctx.level)
        if pause_seconds > 0:
            await pause_fn(pause_seconds)


def roster_summary() -> str:
    lines = ["| Agente | Papel |", "|--------|-------|"]
    for a in SUPERVISOR_ROSTER:
        lines.append(f"| {a['label']} | {a['focus']} |")
    return "\n".join(lines)
