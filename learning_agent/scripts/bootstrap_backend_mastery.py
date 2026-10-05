#!/usr/bin/env python3
"""Bootstrap Backend Mastery — apostila indexada, falhas, grafo."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent.core import errors, graph, knowledge  # noqa: E402

FAILURES = [
    {
        "context": "api.py — handler com lógica de negócio",
        "error": "Implementou consolidação inteira dentro de rota FastAPI — 150+ linhas, untestável.",
        "fix": "Extrair para core/consolidation.py; api só chama consolidate_full_session().",
        "tags": ["failure", "backend", "fastapi", "architecture"],
    },
    {
        "context": "theater — chamada sync SQLite em async",
        "error": "knowledge.add_note() síncrono bloqueou event loop — WS travou durante ciclo.",
        "fix": "run_in_executor(None, lambda: knowledge.add_note(...)) como em run_teaching_cycle.",
        "tags": ["failure", "backend", "async", "sqlite"],
    },
    {
        "context": "API pública — secrets em log",
        "error": "Log de debug imprimiu GROQ_API_KEY ao falhar chat.reply.",
        "fix": "Nunca logar env secrets; mascarar keys; usar logging estruturado sem payload sensível.",
        "tags": ["failure", "backend", "security"],
    },
    {
        "context": "quiz — duplicação sem critério",
        "error": "create_quiz inseriu mesmas perguntas a cada consolidação sem checar existentes.",
        "fix": "Documentar que quizzes são por sessão; ou idempotência por topic prefix Backend —.",
        "tags": ["failure", "backend", "quiz", "data"],
    },
]

GRAPH_EDGES = [
    ("backend-mastery", "fastapi", "implements", 1.0),
    ("backend-mastery", "python-async", "requires", 0.95),
    ("backend-mastery", "sqlite", "persists", 1.0),
    ("backend-mastery", "rest-api", "exposes", 1.0),
    ("fastapi", "pydantic", "validates", 1.0),
    ("fastapi", "theater", "orchestrates", 0.9),
    ("backend-mastery", "websocket", "streams", 0.9),
    ("backend-mastery", "security", "requires", 0.85),
    ("security", "cors", "includes", 0.8),
    ("backend-mastery", "pytest", "verifies", 0.85),
]


def main() -> None:
    note = knowledge.add_note(
        title="[Backend Mastery] Apostila — Python, FastAPI, SQL, arquitetura staff",
        content="""# Backend Mastery — índice Ravenna

## Apostilas
- docs/backend/backend-mastery.md
- docs/backend/backend-mastery-expert.md

## Currículo observador
- `backend-mastery`: 8 trilhas × 3 voltas = 24 ciclos
- Consolidação + 16 quizzes Backend

## Stack do projeto
- FastAPI + Pydantic + SQLite + WebSocket
- core/ (negócio) · api.py (adapters)

## Busca
- `rg "async def" learning_agent/`
- `rg "@app\\." learning_agent/api.py`
""",
        tags=["backend", "fastapi", "python", "sql", "api", "architecture", "theater"],
    )

    for f in FAILURES:
        errors.record_failure(f["context"], f["error"], f["fix"], tags=f["tags"])

    for fr, to, rel, w in GRAPH_EDGES:
        graph.add_edge(fr, to, relation=rel, weight=w, source_ref="bootstrap_backend_mastery")

    print("Bootstrap Backend Mastery concluído:")
    print(f"  nota_id: {note.get('note_id') or note.get('id')}")
    print(f"  falhas: {len(FAILURES)}")
    print(f"  arestas: {len(GRAPH_EDGES)}")
    print("  quizzes: criados na consolidação do observador (24 ciclos)")


if __name__ == "__main__":
    main()
