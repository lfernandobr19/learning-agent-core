"""Consolidação completa do aprendizado — após sessão do modo observador."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from learning_agent import db
from learning_agent.core import (
    backend_mastery_quiz,
    codebase,
    html_details_quiz,
    ide_quiz,
    knowledge,
    remote_app_removed,
    progress,
    reinforce_weak_quiz,
)
from learning_agent.core.theater import TEACHING_TRACKS, get_status
from learning_agent.core.theater_curricula import remoteapp_FRONTEND_VOLTAS, get_curriculum

DEFAULT_SEARCH_QUERIES = [
    ("architecture", "arquitetura camadas FastAPI WebSocket services"),
    ("frontend-excellence", "frontend React Error Boundary React Query Vitest"),
    ("backend-excellence", "backend async fila validação Pydantic FastAPI"),
    ("security", "segurança CORS rate limit autenticação WebSocket"),
    ("testing", "testes pytest Playwright e2e cobertura"),
    ("observability", "observabilidade logs métricas OpenTelemetry health"),
    ("scalability", "escala indexação incremental backpressure WebSocket"),
]

HTML_DETAILS_SEARCH_QUERIES = [
    ("details-structure", "HTML details summary disclosure NeuralReasoningDetails DOM"),
    ("details-react", "ChatPanel realocar details summary React TSX"),
    ("details-a11y", "details name acordeão exclusivo a11y WCAG summary"),
    ("details-css", "remote_app-details CSS summary marker prefers-reduced-motion"),
]

BACKEND_SEARCH_QUERIES = [
    ("http-rest", "HTTP REST API status codes idempotency FastAPI"),
    ("python-async", "Python asyncio run_in_executor async def learning_agent"),
    ("fastapi-patterns", "FastAPI Pydantic WebSocket Depends api.py"),
    ("database-sql", "SQLite get_connection quiz_items learning_notes migrations"),
    ("api-design", "API design pagination errors OpenAPI theater messages"),
    ("security", "backend security CORS JWT rate limit validation secrets"),
    ("testing-observability", "pytest observability health logs metrics FastAPI"),
    ("architecture-staff", "backend architecture layers core consolidation mcp"),
]

REINFORCE_WEAK_SEARCH_QUERIES = [
    ("reinforce-be-http", "HTTP status 422 409 Pydantic API design errors"),
    ("reinforce-be-fastapi", "FastAPI handlers core pytest TestClient theater mock"),
    ("reinforce-be-ops", "security CORS health observability Go Node backend"),
    ("reinforce-fe-details-dom", "NeuralReasoningDetails DOM ChatPanel summary first child"),
    ("reinforce-fe-details-a11y", "remote_app-details a11y prefers-reduced-motion name acordeão"),
    ("reinforce-fe-details-expert", "html details expert disclosure checklist RemoteApp"),
]

remoteapp_SEARCH_QUERIES = [
    ("html-semantic", "HTML semântico landmarks ARIA acessibilidade RemoteApp"),
    ("css-modern", "CSS tokens glass panel Tailwind design system RemoteApp"),
    ("css-animations", "CSS animations keyframes prefers-reduced-motion scanline"),
    ("javascript-patterns", "JavaScript módulos hooks WebSocket TypeScript React"),
    ("canvas-svg", "Canvas SVG Three.js neural core gráficos WebGL"),
    ("gsap-motion", "GSAP GreenSock timeline ScrollTrigger animação"),
    ("remote_app-architecture", "arquitetura frontend Feature-Sliced RemoteApp staff"),
]


def _load_theater_notes(curriculum: str, limit: int = 80) -> list[dict[str, Any]]:
    db.init_db()
    if curriculum == "remote-frontend":
        title_filter = "[RemoteApp Frontend]%"
        tag_hint = "%remote_app%"
    elif curriculum == "html-details-mastery":
        title_filter = "[HTML Details]%"
        tag_hint = "%details%"
    elif curriculum == "backend-mastery":
        title_filter = "[Backend Mastery]%"
        tag_hint = "%backend%"
    elif curriculum == "reinforce-weak":
        title_filter = "[Reforço]%"
        tag_hint = "%reforço%"
    else:
        title_filter = "[Teatro]%"
        tag_hint = "%theater%"
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, content, tags, created_at
            FROM learning_notes
            WHERE (title LIKE ? OR tags LIKE ?)
              AND COALESCE(memory_status, 'active') != 'superseded'
            ORDER BY id DESC LIMIT ?
            """,
            (title_filter, tag_hint, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _unique_tracks_from_notes(
    notes: list[dict[str, Any]],
    tracks: list[dict[str, Any]],
) -> list[str]:
    seen: set[str] = set()
    found: list[str] = []
    for n in notes:
        title = n.get("title", "")
        for t in tracks:
            tid = t["id"]
            if tid in title and tid not in seen:
                seen.add(tid)
                found.append(tid)
    return found or [t["id"] for t in tracks]


def _create_quizzes_for_curriculum(curriculum: str) -> dict[str, Any] | None:
    if curriculum == "remote-frontend":
        return {}
    if curriculum == "html-details-mastery":
        return html_details_quiz.create_html_details_quiz()
    if curriculum == "backend-mastery":
        return backend_mastery_quiz.create_backend_mastery_quiz()
    if curriculum == "reinforce-weak":
        return reinforce_weak_quiz.create_reinforce_weak_quiz()
    return ide_quiz.create_ide_mastery_quiz()


def consolidate_full_session(
    *,
    theater_cycles: int | None = None,
    create_quizzes: bool = True,
    curriculum: str | None = None,
) -> dict[str, Any]:
    """Consolidação completa: progress + buscas + nota mestra + quizzes por currículo."""
    status = get_status()
    cur_id = curriculum or status.get("curriculum", "default")
    cur_meta = get_curriculum(cur_id)
    tracks = cur_meta.get("tracks") or TEACHING_TRACKS
    if cur_id == "remote-frontend":
        search_queries = remoteapp_SEARCH_QUERIES
    elif cur_id == "html-details-mastery":
        search_queries = HTML_DETAILS_SEARCH_QUERIES
    elif cur_id == "backend-mastery":
        search_queries = BACKEND_SEARCH_QUERIES
    elif cur_id == "reinforce-weak":
        search_queries = REINFORCE_WEAK_SEARCH_QUERIES
    else:
        search_queries = DEFAULT_SEARCH_QUERIES

    cycles = theater_cycles if theater_cycles is not None else status.get("cycle", 0)
    voltas = status.get("volta_current") or (cycles // len(tracks) if tracks else 0)
    prog = progress.get_progress()
    theater_notes = _load_theater_notes(cur_id)
    tracks_covered = _unique_tracks_from_notes(theater_notes, tracks)

    search_results: dict[str, list[dict[str, str]]] = {}
    for track_id, query in search_queries:
        hits = knowledge.search(query, limit=4)
        search_results[track_id] = [
            {
                "title": (h.get("metadata") or {}).get("title", h.get("id", "")),
                "snippet": (h.get("content") or "")[:280],
            }
            for h in hits
        ]

    if cur_id == "remote-frontend":
        code_query = "ravenna-ide NeuralCore globals.css ChatPanel glass"
    elif cur_id == "html-details-mastery":
        code_query = "NeuralReasoningDetails ChatPanel ObserverPanel remote_app-details details summary"
    elif cur_id == "backend-mastery":
        code_query = "api.py FastAPI theater consolidation db get_connection async def"
    elif cur_id == "reinforce-weak":
        code_query = (
            "NeuralReasoningDetails api.py health weak_areas remote_app-details "
            "theater_curricula reinforce"
        )
    else:
        code_query = "ravenna-ide frontend backend api"
    code_hits = codebase.search_code(code_query, limit=5)
    code_refs = [
        {
            "path": (h.get("metadata") or {}).get("path", ""),
            "symbol": (h.get("metadata") or {}).get("symbol", ""),
        }
        for h in code_hits
    ]

    if cur_id == "remote-frontend":
        session_label = "RemoteApp Frontend Mastery"
        note_title = "[Consolidacao COMPLETA] RemoteApp Frontend — 5 voltas"
        note_tags = ["consolidacao-completa", "remote_app", "frontend", "theater", "html", "css", "gsap"]
    elif cur_id == "html-details-mastery":
        session_label = "HTML details/summary — maestria RemoteApp"
        note_title = "[Consolidacao COMPLETA] HTML Details — 2 voltas"
        note_tags = ["consolidacao-completa", "html", "details", "summary", "theater", "remote_app", "frontend"]
    elif cur_id == "backend-mastery":
        session_label = "Backend Mastery — Python, FastAPI, SQL, arquitetura staff"
        note_title = "[Consolidacao COMPLETA] Backend Mastery — 3 voltas"
        note_tags = [
            "consolidacao-completa",
            "backend",
            "python",
            "fastapi",
            "sql",
            "theater",
            "api",
            "security",
            "architecture",
        ]
    elif cur_id == "reinforce-weak":
        session_label = "Reforço — áreas fracas (quiz Backend + Details)"
        note_title = "[Consolidacao COMPLETA] Reforço áreas fracas — 2 voltas"
        note_tags = [
            "consolidacao-completa",
            "reforço",
            "quiz",
            "backend",
            "details",
            "theater",
            "weak-areas",
        ]
    else:
        session_label = "Excelência geral (observador)"
        note_title = "[Consolidacao COMPLETA] Sessao observador"
        note_tags = ["consolidacao-completa", "theater", "excelencia", "ravenna-ide"]

    lines: list[str] = [
        f"# Consolidação completa — {session_label}",
        "",
        f"**Data:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Currículo:** {cur_meta.get('title', cur_id)}",
        f"**Ciclos:** {cycles} | **Voltas:** {voltas}/{status.get('voltas_target') or remoteapp_FRONTEND_VOLTAS if cur_id == 'remote-frontend' else '—'}",
        f"**Notas sessão:** {len(theater_notes)} | **Mensagens teatro:** {status.get('messages_sent', 0)}",
        "",
        "## Panorama (`get_progress`)",
        f"- Áreas fracas: {', '.join(prog.get('weak_areas', [])) or 'nenhuma'}",
        f"- Quizzes pendentes: {len(prog.get('due_quizzes', []))}",
        f"- Trilhas cobertas: {', '.join(tracks_covered)}",
        "",
        "## Síntese das aulas",
    ]

    for track in tracks:
        lines.append(f"### {track['level']} (`{track['id']}`)")
        lines.append(f"- **Lição:** {track['lesson'][:400]}{'…' if len(track['lesson']) > 400 else ''}")
        lines.append(f"- **Próximo patamar:** {track['superior']}")
        snippets = search_results.get(track["id"], [])
        if snippets:
            lines.append("- **Evidências no knowledge base:**")
            for s in snippets[:2]:
                lines.append(f"  - {s['title']}: {s['snippet'][:160]}…")
        lines.append("")

    if code_refs:
        lines.append("## Código indexado (RAG)")
        for c in code_refs:
            lines.append(f"- `{c['path']}` {c['symbol']}")
        lines.append("")

    if cur_id == "backend-mastery":
        lines.extend(
            [
                "## Backend Mastery — aplicável no learning-agent",
                "- Camadas: api/mcp → core → db",
                "- Async: executor para SQLite/RAG; wait_for no LLM",
                "- Teatro + consolidação + quizzes por currículo",
                "- WS + REST contratos alinhados ao observador",
                "",
                "## Apostilas",
                "- docs/backend/backend-mastery.md",
                "- docs/backend/backend-mastery-expert.md",
                "",
                "## Multi-linguagem (referência staff)",
                "- Python/FastAPI: stack atual",
                "- Go: throughput, workers; Node/Nest: DI/controllers",
                "- Princípios universais: camadas, contratos, observabilidade",
                "",
                "## Prova de especialista",
                "- 16 quizzes Backend — spaced repetition",
                "- 4 falhas registradas (handlers gordos, async, secrets, quiz)",
                "- Grafo: backend-mastery → fastapi → theater → websocket",
                "",
            ]
        )
    elif cur_id == "reinforce-weak":
        lines.extend(
            [
                "## Reforço — tópicos que falharam no quiz",
                f"- Áreas fracas atuais: {', '.join(prog.get('weak_areas', [])) or 'nenhuma'}",
                "- Backend: status HTTP, Pydantic, camadas FastAPI, testes, segurança, observabilidade",
                "- Details: DOM, realocação chat, React, a11y, CSS marker, motion, cenário expert",
                "",
                "## Apostila",
                "- docs/reinforcement/weak-areas-refocus.md",
                "- docs/backend/backend-mastery.md",
                "- docs/frontend/html-details-summary-expert.md",
                "",
                "## Próximo passo",
                "- Rodar `run_quiz_reinforcement.py` com prefixo Reforço —",
                "- Reavaliar tópicos Backend — e Details — ainda fracos",
                "",
            ]
        )
    elif cur_id == "html-details-mastery":
        lines.extend(
            [
                "## Maestria details/summary — aplicável já",
                "- Localizar: `rg '<details'` + `NeuralReasoningDetails`",
                "- Chat: raciocínio abaixo do `<time>`, fora da bolha",
                "- Observer: `name=\"remote_app-observer-reasoning\"` acordeão exclusivo",
                "- CSS: `.remote_app-details` + `prefers-reduced-motion`",
                "",
                "## Docs de referência",
                "- docs/frontend/html-details-summary.md",
                "- docs/frontend/html-details-summary-expert.md",
                "",
                "## Prova de especialista",
                "- 10 quizzes Details — spaced repetition",
                "- 3 falhas registradas no knowledge base",
                "- Grafo: html-details → disclosure → chatpanel/observerpanel",
                "",
            ]
        )
    elif cur_id == "remote-frontend":
        lines.extend(
            [
                "## Projeto RemoteApp — identidade aplicável",
                "- Fundo `#050510`, grid cyber, glass panels violeta/ciano",
                "- Núcleo neural Three.js como ícone e metáfora visual",
                "- Fontes Orbitron (display) + Rajdhani (body)",
                "- Animações: scanline, border-flow, msg-in, neural-dot",
                "",
                "## Stack ensinada",
                "- HTML semântico + WCAG AA",
                "- CSS tokens, camadas, animações compositor-friendly",
                "- JavaScript/TS: módulos, hooks, WS",
                "- Canvas 2D + SVG + Three.js híbrido",
                "- GSAP timelines + ScrollTrigger",
                "- Arquitetura Feature-Sliced staff",
                "",
                "## Plano de aplicação (quando solicitado)",
                "1. Tokens CSS + a11y",
                "2. Motion + prefers-reduced-motion",
                "3. Hooks extraídos (useChat)",
                "4. SVG ícone RemoteApp",
                "5. GSAP entrada opcional",
                "6. FSD incremental com ADRs",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Objetivo final — IDE completa",
                "Explorer, Monaco, terminal PTY, anexos, MCP, extensões, Git, LSP.",
                "",
                "## Plano de ação (6 fases)",
                "1. Layout shell + tabs",
                "2. Explorer + Monaco",
                "3. Terminal PTY",
                "4. Upload/anexos + RAG",
                "5. MCP + LSP",
                "6. Extensões + Git + e2e",
                "",
            ]
        )

    lines.append("## Notas brutas da sessão (últimas 8)")
    for n in theater_notes[:8]:
        lines.append(f"- {n.get('title', '')}")

    body = "\n".join(lines)
    note = knowledge.add_note(note_title, body, tags=note_tags)

    quiz_result: dict[str, Any] | None = None
    if create_quizzes:
        quiz_result = _create_quizzes_for_curriculum(cur_id)

    if cur_id == "remote-frontend":
        quiz_label = "RemoteApp Frontend"
    elif cur_id == "html-details-mastery":
        quiz_label = "HTML details/summary"
    elif cur_id == "backend-mastery":
        quiz_label = "Backend Mastery"
    elif cur_id == "reinforce-weak":
        quiz_label = "Reforço áreas fracas"
    else:
        quiz_label = "IDE completa"

    return {
        "success": True,
        "curriculum": cur_id,
        "consolidation_note_id": note.get("note_id") or note.get("id"),
        "theater_cycles": cycles,
        "theater_notes_count": len(theater_notes),
        "tracks_covered": tracks_covered,
        "search_topics": list(search_results.keys()),
        "code_refs": code_refs,
        "quiz": quiz_result,
        "quiz_count": quiz_result.get("total", 0) if quiz_result else 0,
        "quiz_type": quiz_label,
        "ide_quiz": quiz_result if cur_id != "remote-frontend" else None,
        "ide_quiz_count": quiz_result.get("total", 0) if quiz_result and cur_id != "remote-frontend" else 0,
        "remote_app_removed": quiz_result if cur_id == "remote-frontend" else None,
        "remote_app_removed": quiz_result.get("total", 0) if quiz_result and cur_id == "remote-frontend" else 0,
        "weak_areas": prog.get("weak_areas", []),
        "summary": (
            f"Consolidação {session_label}: {len(theater_notes)} notas, "
            f"{len(tracks_covered)} trilhas, nota mestra salva, "
            f"{quiz_result.get('total', 0) if quiz_result else 0} quizzes complexos ({quiz_label})."
        ),
    }


async def consolidate_and_broadcast() -> dict[str, Any]:
    """Consolidação + anúncio no painel observador."""
    from learning_agent.core.supervision_agents import SupervisionContext, broadcast_supervision_round
    from learning_agent.core.theater import _broadcast
    from learning_agent.ide import ravenna_ide

    result = consolidate_full_session()
    cur_id = result.get("curriculum", "default")
    is_remoteapp = cur_id == "remote-frontend"
    is_details = cur_id == "html-details-mastery"
    is_backend = cur_id == "backend-mastery"
    is_reinforce = cur_id == "reinforce-weak"

    if is_remoteapp:
        quiz_topics = "HTML, CSS, animações, JS, Canvas/SVG, GSAP, arquitetura RemoteApp"
        session_label = "RemoteApp Frontend Mastery"
    elif is_details:
        quiz_topics = "details/summary, DOM, React, a11y, CSS RemoteApp"
        session_label = "HTML details/summary — maestria RemoteApp"
    elif is_backend:
        quiz_topics = "HTTP/REST, Python async, FastAPI, SQL, API design, segurança, testes, arquitetura"
        session_label = "Backend Mastery"
    elif is_reinforce:
        quiz_topics = "status HTTP, FastAPI/testes, segurança/health, DOM/React, a11y/CSS, expert disclosure"
        session_label = "Reforço áreas fracas"
    else:
        quiz_topics = "explorer, terminal, anexos, MCP"
        session_label = "Sessão observador"

    qcount = result.get("quiz_count", 0)
    await broadcast_supervision_round(
        SupervisionContext(
            level="Consolidação completa",
            topic=session_label,
            process="consolidation",
            mentor_directive=(
                f"Ravenna: internalize nota mestra #{result.get('consolidation_note_id')} "
                f"e os {qcount} quizzes antes de novas features."
            ),
            reviewer_focus=result.get("summary", ""),
            extra={"quiz_count": qcount},
        ),
        broadcast=_broadcast,
        pause_seconds=0.4,
    )

    await ravenna_ide.broadcast_theater(
        {
            "id": f"consolidation-{datetime.now(timezone.utc).timestamp()}",
            "role": "system",
            "agent": "Consolidação",
            "content": (
                f"✓ Consolidação completa — {session_label}.\n"
                f"Ciclos: {result['theater_cycles']} | Notas: {result['theater_notes_count']}\n"
                f"Nota mestra #{result.get('consolidation_note_id')} salva.\n"
                f"Quizzes complexos: {qcount} perguntas ({quiz_topics})\n"
                f"{result['summary']}"
            ),
            "level": "Consolidação completa",
            "reasoning": "get_progress + search_knowledge + quizzes por currículo",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    quiz_data = result.get("quiz") or {}
    preview_count = min(5, qcount)
    for i, q in enumerate((quiz_data.get("questions") or [])[:preview_count]):
        await ravenna_ide.broadcast_theater(
            {
                "id": f"quiz-preview-{q.get('id', i)}",
                "role": "mentor",
                "agent": "Quiz Master",
                "content": (
                    f"📝 Quiz {i + 1}/{qcount} — {q.get('topic', 'Avaliação')}\n\n"
                    f"{q.get('question', '')}"
                ),
                "level": (
                    "RemoteApp Frontend"
                    if is_remoteapp
                    else "HTML Details"
                    if is_details
                    else "Backend Mastery"
                    if is_backend
                    else "Reforço"
                    if is_reinforce
                    else "Avaliação IDE completa"
                ),
                "reasoning": "Responda no chat ou via quiz-master; gabarito no spaced repetition",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    if is_remoteapp:
        ravenna_msg = (
            f"Consolidei as 5 voltas do RemoteApp Frontend e recebi {qcount} desafios sobre "
            "HTML, CSS, animações, JavaScript, Canvas, SVG, GSAP e arquitetura staff. "
            "Quando você pedir, aplico no código incrementalmente."
        )
    elif is_details:
        ravenna_msg = (
            f"Consolidei a maestria em `<details>`/`<summary>` e recebi {qcount} desafios. "
            "Agora localizo disclosures com `NeuralReasoningDetails`, realoco sem quebrar o DOM "
            "e aplico acordeão exclusivo no observador. Pronta para refatorar sem regressão."
        )
    elif is_backend:
        ravenna_msg = (
            f"Consolidei Backend Mastery e recebi {qcount} desafios sobre HTTP, Python async, "
            "FastAPI, SQL, APIs, segurança e arquitetura staff. "
            "Aplico camadas api→core→db, contratos WS/REST e boas práticas no learning-agent."
        )
    elif is_reinforce:
        ravenna_msg = (
            f"Reforcei os tópicos que falharam no quiz e recebi {qcount} desafios de reforço. "
            "Foco em status HTTP, camadas FastAPI, disclosures no RemoteApp e a11y. "
            "Pronta para reavaliar e reduzir weak_areas."
        )
    else:
        ravenna_msg = (
            f"Consolidei a sessão e recebi {qcount} desafios complexos para provar que consigo "
            "estruturar uma IDE completa. Vou estudar cada quiz e aplicar no roadmap de 6 fases."
        )

    await ravenna_ide.broadcast_theater(
        {
            "id": f"consolidation-ravenna-{datetime.now(timezone.utc).timestamp()}",
            "role": "ravenna",
            "agent": "Ravenna",
            "content": ravenna_msg,
            "level": "Consolidação completa",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result
