"""Modo Observador — agentes ensinam a Ravenna em níveis superiores ao código atual."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from learning_agent.core import chat, codebase, knowledge
from learning_agent.core.supervision_agents import SupervisionContext, broadcast_supervision_round
from learning_agent.core.theater_curricula import get_curriculum, volta_info


class TheaterHTTPError(Exception):
    """Erro de contrato HTTP para rotas REST (mapeado em api.py)."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail)


# Níveis superiores ao que a Ravenna IDE implementou hoje
TEACHING_TRACKS: list[dict[str, Any]] = [
    {
        "id": "architecture",
        "level": "Arquitetura sênior",
        "agent": "architect",
        "agent_label": "Arquiteta de Sistemas",
        "search": "ravenna-ide api websocket fastapi",
        "lesson": (
            "Separe claramente camadas: UI (React) → transporte (REST/WS) → domínio (learning_agent). "
            "Evite lógica de negócio no handler WebSocket; use serviços testáveis. "
            "Contratos OpenAPI versionados e DTOs explícitos superam endpoints ad-hoc."
        ),
        "superior": (
            "Próximo nível: módulo `services/` com interfaces, injeção de dependência no FastAPI, "
            "e event bus interno para desacoplar chat, teatro e sync."
        ),
    },
    {
        "id": "frontend-excellence",
        "level": "Frontend excelente",
        "agent": "senior-fe",
        "agent_label": "Eng. Frontend Sênior",
        "search": "ChatPanel App.tsx components",
        "lesson": (
            "Componentes pequenos, estado elevado com hooks dedicados, Error Boundaries e loading skeletons. "
            "Virtualize listas longas no observador; memoize painéis pesados (Three.js). "
            "Acessibilidade: roles ARIA, foco no teclado, contraste WCAG AA."
        ),
        "superior": (
            "Próximo nível: React Query para API, Zustand para theater+chat, testes Vitest + Testing Library, "
            "e Storybook para cada painel da IDE."
        ),
    },
    {
        "id": "backend-excellence",
        "level": "Backend excelente",
        "agent": "senior-be",
        "agent_label": "Eng. Backend Sênior",
        "search": "ide.py chat.reply api",
        "lesson": (
            "Handlers async finos; CPU-bound em thread pool; validação Pydantic em toda entrada. "
            "Timeouts e circuit breaker nas chamadas LLM. "
            "Idempotência em rotas de aprendizado e filas para tarefas longas."
        ),
        "superior": (
            "Próximo nível: fila (ARQ/Celery) para indexação e destilação, cache Redis para RAG, "
            "e testes de contrato pytest + schemathesis."
        ),
    },
    {
        "id": "security",
        "level": "Segurança",
        "agent": "reviewer",
        "agent_label": "Revisor de Segurança",
        "search": "cors env api",
        "lesson": (
            "CORS `*` é aceitável só em dev; em produção restrinja origens. "
            "Nunca exponha `.env` no frontend. Rate limit em `/api/chat` e WebSocket auth. "
            "Sanitize mensagens do teatro antes de persistir."
        ),
        "superior": (
            "Próximo nível: JWT ou API key por canal, secrets via vault, auditoria de tools MCP."
        ),
    },
    {
        "id": "testing",
        "level": "Testes automatizados",
        "agent": "mentor",
        "agent_label": "Mentor de Qualidade",
        "search": "proofs pytest test",
        "lesson": (
            "Cada feature nova exige prova real: pytest para API/teatro, Vitest para UI. "
            "Teste WebSocket com cliente fake; snapshot dos payloads do observador."
        ),
        "superior": (
            "Próximo nível: CI com cobertura mínima 80%, Playwright e2e na IDE, mutation testing em regras críticas."
        ),
    },
    {
        "id": "observability",
        "level": "Observabilidade",
        "agent": "architect",
        "agent_label": "Arquiteta de Sistemas",
        "search": "health dashboard logging",
        "lesson": (
            "Logs estruturados (JSON) com correlation_id por sessão do teatro. "
            "Métricas: latência LLM, mensagens/min, falhas de broadcast. "
            "Health checks separados: API, Ollama, Chroma."
        ),
        "superior": (
            "Próximo nível: OpenTelemetry traces do chat ao index RAG, dashboard Grafana, alertas."
        ),
    },
    {
        "id": "scalability",
        "level": "Escala e performance",
        "agent": "senior-be",
        "agent_label": "Eng. Backend Sênior",
        "search": "chromadb rag index",
        "lesson": (
            "Indexação incremental, não full reindex. Chunking adaptativo e embeddings locais opcionais. "
            "WebSocket: backpressure se cliente lento; limite de mensagens no observador."
        ),
        "superior": (
            "Próximo nível: workers horizontais, read replicas SQLite→Postgres, CDN no frontend estático."
        ),
    },
]

_state: dict[str, Any] = {
    "running": False,
    "cycle": 0,
    "track_index": 0,
    "messages_sent": 0,
    "indexed": False,
    "max_cycles": None,
    "curriculum": "default",
    "voltas_target": None,
    "recent_messages": [],
}

_RECENT_LIMIT = 120

_task: asyncio.Task[None] | None = None
_stop = asyncio.Event()


def _active_tracks() -> list[dict[str, Any]]:
    cur = get_curriculum(_state.get("curriculum", "default"))
    if cur.get("tracks"):
        return cur["tracks"]
    return TEACHING_TRACKS


def get_status() -> dict[str, Any]:
    max_cycles = _state.get("max_cycles")
    cycle = _state["cycle"]
    tracks = _active_tracks()
    tracks_total = len(tracks)
    cur = get_curriculum(_state.get("curriculum", "default"))
    vi = volta_info(cycle, tracks_total)
    remaining = (max_cycles - cycle) if max_cycles else None
    cycle_est = cur.get("cycle_seconds_est", 75)
    return {
        "running": _state["running"],
        "cycle": cycle,
        "track_index": _state["track_index"],
        "messages_sent": _state["messages_sent"],
        "tracks_total": tracks_total,
        "max_cycles": max_cycles,
        "cycles_remaining": remaining,
        "curriculum": _state.get("curriculum", "default"),
        "curriculum_title": cur.get("title", ""),
        "voltas_target": _state.get("voltas_target"),
        "volta_current": vi["volta"],
        "volta_cycle": vi["volta_cycle"],
        "estimated_minutes_total": cur.get("estimated_minutes"),
        "estimated_minutes_remaining": (
            (remaining * cycle_est) // 60 if remaining is not None else None
        ),
        "current_track": (
            tracks[_state["track_index"] % tracks_total]["id"] if tracks else None
        ),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _broadcast(
    role: str,
    agent: str,
    content: str,
    *,
    level: str = "",
    reasoning: str = "",
) -> None:
    from learning_agent.ide import ravenna_ide

    payload = {
        "id": f"theater-{uuid.uuid4().hex[:10]}",
        "role": role,
        "agent": agent,
        "content": content,
        "level": level,
        "reasoning": reasoning,
        "timestamp": _now_iso(),
    }
    await ravenna_ide.broadcast_theater(payload)
    _state["messages_sent"] += 1
    recent: list[dict[str, Any]] = _state.setdefault("recent_messages", [])
    recent.append(payload)
    if len(recent) > _RECENT_LIMIT:
        _state["recent_messages"] = recent[-_RECENT_LIMIT:]


def get_recent_messages(limit: int = 80) -> list[dict[str, Any]]:
    msgs = _state.get("recent_messages") or []
    return msgs[-limit:] if limit else list(msgs)


def _code_snippet(track: dict[str, Any], limit: int = 2) -> str:
    hits = codebase.search_code(track["search"], limit=limit)
    if not hits:
        return ""
    lines: list[str] = []
    for hit in hits[:limit]:
        meta = hit.get("metadata", {})
        path = meta.get("path", meta.get("file", "?"))
        symbol = meta.get("symbol", "")
        excerpt = (hit.get("content") or hit.get("text") or "")[:200].strip()
        if excerpt:
            lines.append(f"• `{path}` {symbol}: {excerpt}…")
    return "\n".join(lines)


async def _pause(seconds: float) -> None:
    try:
        await asyncio.wait_for(_stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def run_teaching_cycle(cycle_num: int, track: dict[str, Any]) -> None:
    level = track["level"]
    snippet = _code_snippet(track)
    tracks = _active_tracks()
    vi = volta_info(cycle_num, len(tracks))
    volta_label = ""
    if _state.get("voltas_target"):
        volta_label = f" · Volta {vi['volta']}/{_state['voltas_target']} ({vi['volta_cycle']}/{len(tracks)})"

    await _broadcast(
        "system",
        "Sistema",
        f"— Ciclo {cycle_num}{volta_label} · {level} —",
        level=level,
    )
    await _pause(0.8)

    lesson = track["lesson"]
    if snippet:
        lesson = f"{lesson}\n\n**No seu código hoje:**\n{snippet}"

    await _broadcast(track["agent"], track["agent_label"], lesson, level=level)
    await _pause(0.8)

    await broadcast_supervision_round(
        SupervisionContext(
            level=level,
            topic=track["id"],
            process="theater",
            lesson=track["lesson"],
            superior=track["superior"],
            track_id=track["id"],
            reviewer_focus=(
                f"Gap atual: a IDE cumpre o MVP, mas falta o patamar **{level}**. "
                f"Priorize: {track['superior']}"
            ),
            mentor_directive=f"Ravenna: aplique a lição de **{level}** no próximo ciclo de implementação.",
        ),
        broadcast=_broadcast,
        pause_fn=_pause,
        pause_seconds=0.45,
    )
    await _pause(0.4)

    cur = get_curriculum(_state.get("curriculum", "default"))
    prefix = cur.get("note_prefix", "[Teatro]")
    tags = list(cur.get("tags", ["theater", "ravenna-ide"]))
    if track["id"] not in tags:
        tags.append(track["id"])

    note_title = f"{prefix} {track['id']} — ciclo {cycle_num}"
    if vi["volta"] > 0:
        note_title += f" (volta {vi['volta']})"
    note_body = f"{track['lesson']}\n\n## Nível superior\n{track['superior']}"
    if snippet:
        note_body += f"\n\n## Referências\n{snippet}"

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: knowledge.add_note(note_title, note_body, tags=tags),
    )

    await _broadcast(
        "system",
        "Sistema",
        f"Nota #{note_title} salva no knowledge base.",
        level=level,
    )
    await _pause(0.5)

    prompt = (
        f"[Teatro — máximo 3 frases, feminino] Absorvi a lição sobre {level}. "
        f"O que aplico na próxima versão da IDE?"
    )
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: chat.reply(
                    prompt,
                    channel="theater",
                    user_id="observer",
                    include_context=False,
                ),
            ),
            timeout=45.0,
        )
        if result.get("success"):
            reply = (result.get("reply") or "")[:400]
            reasoning = f"Modelo: {result.get('model', '?')}"
        else:
            reply = f"Vou internalizar e retomar quando o LLM responder: {result.get('error', '')[:120]}"
            reasoning = result.get("hint", "")
    except asyncio.TimeoutError:
        reply = f"Lição registrada sobre {level}. Vou aplicar no próximo ciclo de implementação."
        reasoning = "LLM em timeout — nota salva no knowledge base."

    await _broadcast("ravenna", "Ravenna", reply, level=level, reasoning=reasoning)


async def _index_in_background() -> None:
    if _state["indexed"]:
        return
    loop = asyncio.get_event_loop()
    await _broadcast(
        "system",
        "Sistema",
        "Indexando `ravenna-ide/` em segundo plano — ensino começa já.",
    )
    try:
        await loop.run_in_executor(
            None,
            lambda: codebase.index_codebase(
                ["ravenna-ide/frontend/src", "learning_agent"],
                extra_tags=["ravenna-ide", "theater"],
            ),
        )
        _state["indexed"] = True
        await _broadcast(
            "system",
            "Sistema",
            "Indexação concluída — lições agora citam trechos reais do seu código.",
        )
    except Exception as exc:
        await _broadcast("system", "Sistema", f"Indexação falhou (seguindo sem RAG de código): {exc}")


async def _teaching_loop() -> None:
    global _state
    _state["running"] = True
    _stop.clear()

    if not _state["indexed"]:
        asyncio.create_task(_index_in_background())

    tracks = _active_tracks()
    cur = get_curriculum(_state.get("curriculum", "default"))
    intro = cur.get("title", "Sessão de excelência")
    if _state.get("curriculum") == "remote-frontend":
        await _broadcast(
            "cursor",
            "Cursor",
            (
                "🜂 **RemoteApp Frontend Mastery** — sessão ao vivo iniciada.\n"
                "HTML semântico · CSS moderno & animações · JavaScript avançado · "
                "Canvas & SVG · GSAP · Arquitetura frontend staff.\n"
                "Base visual: núcleo neural, glass cyber, violeta/ciano."
            ),
            level="RemoteApp",
        )
    elif _state.get("curriculum") == "html-details-mastery":
        await _broadcast(
            "cursor",
            "Cursor",
            (
                "◇ **HTML details/summary — maestria RemoteApp** — sessão focada iniciada.\n"
                "Estrutura DOM · realocação React · a11y/acordeão exclusivo · CSS `.remote_app-details`.\n"
                "Referência: `NeuralReasoningDetails.tsx` + docs/frontend/html-details-summary*.md"
            ),
            level="HTML Details",
        )
    elif _state.get("curriculum") == "backend-mastery":
        await _broadcast(
            "cursor",
            "Cursor",
            (
                "⚙ **Backend Mastery** — sessão iniciada.\n"
                "HTTP/REST · Python async · FastAPI · SQL · design de API · segurança · "
                "testes/observabilidade · arquitetura staff.\n"
                "Apostila: `docs/backend/backend-mastery.md` + expert."
            ),
            level="Backend",
        )
    elif _state.get("curriculum") == "reinforce-weak":
        await _broadcast(
            "cursor",
            "Cursor",
            (
                "↻ **Reforço — áreas fracas** — sessão focada iniciada.\n"
                "HTTP/status · FastAPI/testes · segurança/health · DOM/React · a11y/CSS · expert details.\n"
                "Baseado na avaliação de quiz #213. Apostila: `docs/reinforcement/weak-areas-refocus.md`."
            ),
            level="Reforço",
        )
    elif _state.get("curriculum") == "ide-testing-mastery":
        await _broadcast(
            "cursor",
            "Cursor",
            (
                "✓ **IDE Testing Mastery** — supervisão de qualidade iniciada.\n"
                "Pirâmide: pytest → Vitest → Playwright → run_proofs.\n"
                "Apostila: `docs/frontend/ide-testing-mastery.md` · runner: `supervise-ide-tests`."
            ),
            level="IDE Testing",
        )
    else:
        await _broadcast(
            "cursor",
            "Cursor",
            "Sessão ao vivo iniciada — vamos elevar a Ravenna acima do MVP da IDE em front, back e arquitetura.",
            level="Excelência",
        )
    await _pause(0.6)

    await broadcast_supervision_round(
        SupervisionContext(
            level=intro,
            topic=_state.get("curriculum", "default"),
            process="session",
            mentor_directive=(
                "Ravenna: todos os agentes supervisionam cada ciclo — "
                "registre notas, aplique no código e confirme com provas."
            ),
        ),
        broadcast=_broadcast,
        pause_fn=_pause,
        pause_seconds=0.35,
    )
    await _pause(0.4)

    if _state.get("max_cycles"):
        mc = _state["max_cycles"]
        voltas = mc // len(tracks)
        est_min = cur.get("estimated_minutes") or (mc * cur.get("cycle_seconds_est", 75)) // 60
        await _broadcast(
            "system",
            "Sistema",
            (
                f"📋 **{intro}**\n"
                f"Meta: **{mc} ciclos** = **{voltas} voltas** × {len(tracks)} trilhas.\n"
                f"Tempo estimado: **~{est_min} minutos** (pode variar com o LLM local)."
            ),
            level=(
                "RemoteApp"
                if _state.get("curriculum") == "remote-frontend"
                else "HTML Details"
                if _state.get("curriculum") == "html-details-mastery"
                else "Backend"
                if _state.get("curriculum") == "backend-mastery"
                else "Reforço"
                if _state.get("curriculum") == "reinforce-weak"
                else "IDE Testing"
                if _state.get("curriculum") == "ide-testing-mastery"
                else "Excelência"
            ),
        )
        await _pause(0.8)

    while not _stop.is_set():
        max_cycles = _state.get("max_cycles")
        next_cycle = _state["cycle"] + 1
        if max_cycles and next_cycle > max_cycles:
            break
        _state["cycle"] = next_cycle
        track = tracks[_state["track_index"] % len(tracks)]
        _state["track_index"] += 1
        try:
            await run_teaching_cycle(_state["cycle"], track)
        except Exception as exc:
            await _broadcast("system", "Sistema", f"Erro no ciclo (continuando): {exc}")
        if _state.get("max_cycles") and _state["cycle"] >= _state["max_cycles"]:
            break
        await _pause(1.8)

    _state["running"] = False
    if _state.get("max_cycles") and _state["cycle"] >= _state["max_cycles"] and not _stop.is_set():
        await _broadcast(
            "system",
            "Sistema",
            f"Meta atingida: {_state['max_cycles']} ciclos concluídos. Iniciando consolidação e quizzes…",
            level="Excelência",
        )
        from learning_agent.core.consolidation import consolidate_and_broadcast

        try:
            await consolidate_and_broadcast()
        except Exception as exc:
            await _broadcast("system", "Sistema", f"Consolidação falhou: {exc}")


def _reset_counters() -> None:
    _state["cycle"] = 0
    _state["track_index"] = 0
    _state["messages_sent"] = 0
    _state["recent_messages"] = []


async def start_theater(
    *,
    max_cycles: int | None = None,
    reset: bool = False,
    curriculum: str = "default",
) -> dict[str, Any]:
    global _task
    if max_cycles is not None and max_cycles < 1:
        raise TheaterHTTPError(422, "max_cycles deve ser >= 1")

    cur = get_curriculum(curriculum)
    if curriculum not in (
        "default",
        "remote-frontend",
        "html-details-mastery",
        "backend-mastery",
        "reinforce-weak",
        "ide-testing-mastery",
    ):
        raise TheaterHTTPError(404, f"Currículo desconhecido: {curriculum}")

    if _task and not _task.done():
        if reset:
            await stop_theater(consolidate=False)
        else:
            if curriculum != _state.get("curriculum"):
                raise TheaterHTTPError(
                    409,
                    "Teatro já rodando com outro currículo. Pare ou use reset=true.",
                    extra=get_status(),
                )
            if max_cycles is not None:
                _state["max_cycles"] = max_cycles
            return {
                "success": True,
                "status": "already_running",
                "max_cycles_set": max_cycles,
                **get_status(),
            }

    if reset:
        _reset_counters()
    _state["curriculum"] = curriculum
    if max_cycles is not None:
        _state["max_cycles"] = max_cycles
    elif cur.get("max_cycles_default"):
        _state["max_cycles"] = cur["max_cycles_default"]
    if cur.get("voltas_default"):
        _state["voltas_target"] = cur["voltas_default"]
    else:
        tracks = cur["tracks"] or TEACHING_TRACKS
        mc = _state.get("max_cycles")
        _state["voltas_target"] = (mc // len(tracks)) if mc else None

    _stop.clear()
    _task = asyncio.create_task(_teaching_loop())
    return {"success": True, "status": "started", **get_status()}


async def stop_theater(*, consolidate: bool = True) -> dict[str, Any]:
    global _task
    _stop.set()
    if _task:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except asyncio.TimeoutError:
            _task.cancel()
    _state["running"] = False
    await _broadcast("system", "Sistema", "Modo observador pausado.")
    result: dict[str, Any] = {"success": True, "status": "stopped", **get_status()}
    if consolidate and _state.get("cycle", 0) > 0:
        from learning_agent.core.consolidation import consolidate_and_broadcast

        try:
            result["consolidation"] = await consolidate_and_broadcast()
        except Exception as exc:
            result["consolidation_error"] = str(exc)
    return result


async def post_agent_message(
    role: str,
    agent: str,
    content: str,
    *,
    level: str = "",
    reasoning: str = "",
) -> dict[str, Any]:
    await _broadcast(role, agent, content, level=level, reasoning=reasoning)
    return {"success": True, "posted": True}
