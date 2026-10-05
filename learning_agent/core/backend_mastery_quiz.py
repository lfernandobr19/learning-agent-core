"""Quizzes — Backend Mastery (Python, FastAPI, SQL, arquitetura staff)."""

from __future__ import annotations

from typing import Any

from learning_agent.core import quiz as quiz_core

BACKEND_MASTERY_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": "Backend — HTTP & REST",
        "question": (
            "Por que POST /api/theater/start não é idempotente e como garantir comportamento "
            "previsível ao reiniciar com reset=true vs reset=false?"
        ),
        "answer": (
            "POST cria efeito colateral (nova sessão, contadores). reset=true zera estado; "
            "reset=false retoma ou falha se currículo diferente. Para idempotência real use "
            "Idempotency-Key ou GET para leitura de status; documentar contrato no OpenAPI."
        ),
    },
    {
        "topic": "Backend — Status HTTP",
        "question": (
            "Mapeie cenários do learning-agent: validação Pydantic falha, teatro já rodando, "
            "LLM timeout, recurso não encontrado — para quais status HTTP?"
        ),
        "answer": (
            "422 Unprocessable Entity (Pydantic); 409 Conflict ou 400 com mensagem clara "
            "(teatro já ativo); 504 Gateway Timeout ou 503 (LLM); 404 Not Found (recurso/rota). "
            "Nunca 200 com erro no body."
        ),
    },
    {
        "topic": "Backend — Python async",
        "question": (
            "Por que run_teaching_cycle usa run_in_executor para knowledge.add_note e "
            "asyncio.wait_for no chat.reply? O que acontece se chamar SQLite sync dentro de async sem executor?"
        ),
        "answer": (
            "SQLite sync bloqueia o event loop — atrasa WS e outras requisições. "
            "run_in_executor isola I/O bloqueante. wait_for evita teatro travado em LLM lento. "
            "Alternativa: aiosqlite + pool async."
        ),
    },
    {
        "topic": "Backend — FastAPI camadas",
        "question": (
            "Onde deve viver a lógica de consolidate_full_session e por que api.py deve permanecer fino?"
        ),
        "answer": (
            "Em learning_agent/core/consolidation.py. api.py só expõe HTTP/MCP — adapters. "
            "Facilita testes unitários, reuso MCP+REST, e evita handlers de 200+ linhas. "
            "Padrão: api → core → db."
        ),
    },
    {
        "topic": "Backend — Pydantic & contratos",
        "question": (
            "Como ChatRequest e TheaterPostRequest protegem a API e o que validar além de tipos?"
        ),
        "answer": (
            "Tipos + constraints (min/max length, enums de role). Rejeição automática 422. "
            "Validar também: tamanho de content, caracteres perigosos, rate por user_id, "
            "curriculum em whitelist (default, remote-frontend, backend-mastery, etc.)."
        ),
    },
    {
        "topic": "Backend — SQLite & transações",
        "question": (
            "Por que quiz_items e learning_notes devem usar queries parametrizadas e context manager "
            "em get_connection()?"
        ),
        "answer": (
            "Parâmetros ? evitam SQL injection. Context manager garante commit/rollback e fechamento. "
            "Evita locked database por conexões abertas. Em alta carga migrar para Postgres com pool."
        ),
    },
    {
        "topic": "Backend — SQL & índices",
        "question": (
            "Quais colunas em quiz_items e learning_notes merecem índice no learning-agent e por quê?"
        ),
        "answer": (
            "quiz_items: topic, next_review (spaced repetition due queries). "
            "learning_notes: created_at, tags/title prefix para consolidação. "
            "Índice só onde há filtro/ORDER BY frequente — medir com EXPLAIN QUERY PLAN."
        ),
    },
    {
        "topic": "Backend — Design de API",
        "question": (
            "Como projetar GET /api/theater/messages com limit cap e histórico WS consistente?"
        ),
        "answer": (
            "limit=min(query, 120) no servidor; ordenação estável por timestamp. "
            "WS envia novas mensagens; GET recupera buffer recent_messages ao reconectar. "
            "Documentar schema JSON de cada tipo de mensagem no observador."
        ),
    },
    {
        "topic": "Backend — WebSocket",
        "question": (
            "Explique o papel de ravenna_ide.broadcast_theater vs REST POST /api/theater/message. "
            "Quando usar cada um?"
        ),
        "answer": (
            "broadcast_theater: push em tempo real para clientes WS conectados (teatro interno). "
            "POST message: agentes externos (MCP Cursor) injetam mensagem via HTTP. "
            "Ambos devem normalizar para mesmo schema Message no frontend."
        ),
    },
    {
        "topic": "Backend — Segurança",
        "question": (
            "Lista de verificações ao expor learning-agent API na rede local vs internet."
        ),
        "answer": (
            "Local: CORS localhost, sem secrets em logs. Internet: auth JWT/API key, HTTPS, "
            "rate limit, CORS restrito, validar uploads, rotacionar keys Groq, "
            "não expor /docs sem auth, firewall na porta 8000."
        ),
    },
    {
        "topic": "Backend — Testes",
        "question": (
            "Estratégia pytest para theater.start_theater: o que mockar (LLM, DB) e o que testar de integração?"
        ),
        "answer": (
            "Unit: get_curriculum, volta_info, _load_theater_notes com DB em memória. "
            "Mock: chat.reply e LLM. Integração: TestClient start/status/stop com max_cycles=1. "
            "E2E opcional: Playwright observador + API real."
        ),
    },
    {
        "topic": "Backend — Observabilidade",
        "question": (
            "Quais SLIs mínimos para API Ravenna e como health check agregaria teatro + LLM + DB?"
        ),
        "answer": (
            "SLIs: latência p95 /api/chat, taxa erro 5xx, WS conexões ativas, teatro running. "
            "Health: SQLite ping, Ollama/Groq reachable, theater state opcional. "
            "Logs JSON com request_id; métricas Prometheus se deploy contíiner."
        ),
    },
    {
        "topic": "Backend — Go vs Python",
        "question": (
            "Quando escolher Go para um serviço backend em vez de FastAPI no ecossistema Ravenna?"
        ),
        "answer": (
            "Go: proxy de alta throughput, workers de fila, binário único deploy. "
            "Python: ML/LLM, RAG, produtividade FastAPI, ecossistema atual do learning-agent. "
            "Staff: polyglot com contratos OpenAPI/Protobuf entre serviços."
        ),
    },
    {
        "topic": "Backend — Node/NestJS",
        "question": (
            "Paralelo entre módulos NestJS (controllers/providers) e estrutura learning_agent/core/."
        ),
        "answer": (
            "Controller≈api.py routes; Service≈core/theater.py; Repository≈db.py. "
            "DI Nest≈FastAPI Depends. Guards≈middleware auth. "
            "Mesma regra: controller fino, domínio em services."
        ),
    },
    {
        "topic": "Backend — Arquitetura staff",
        "question": (
            "Como adicionar currículo backend-mastery sem duplicar lógica entre theater_curricula, "
            "consolidation e quiz?"
        ),
        "answer": (
            "Single source: theater_curricula.CURRICULA. consolidation importa get_curriculum + "
            "backend_mastery_quiz.create. theater.py whitelist curriculum id. "
            "DRY: search queries e note_prefix no meta do currículo, não espalhados."
        ),
    },
    {
        "topic": "Backend — Cenário especialista",
        "question": (
            "Projete endpoint POST /api/quiz/answer com validação, SM-2 update, nota de aprendizado "
            "e broadcast opcional — ordem de camadas e falhas a tratar."
        ),
        "answer": (
            "1) Pydantic QuizAnswerRequest; 2) core/quiz.record_answer; 3) db transação SM-2; "
            "4) knowledge.add_note se streak; 5) ide broadcast opcional. "
            "Falhas: 404 item, 422 body, 500 db — sem partial commit. Testes unit + TestClient."
        ),
    },
]


def create_backend_mastery_quiz() -> dict[str, Any]:
    """Cria quizzes Backend Mastery (spaced repetition)."""
    result = quiz_core.insert_curriculum_questions(BACKEND_MASTERY_QUESTIONS)
    return {
        "topic": "Backend Mastery — maestria Ravenna",
        "total": result["total"],
        "skipped": result.get("skipped", 0),
        "questions": result["questions"],
        "goal": (
            "Validar HTTP/REST, Python async, FastAPI, SQL, APIs, segurança, testes, "
            "observabilidade e arquitetura staff no learning-agent."
        ),
    }
