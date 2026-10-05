"""Quizzes complexos — capacidade de estruturar uma IDE completa."""

from __future__ import annotations

from typing import Any

from learning_agent import db
# Objetivo final: IDE com explorer, editor, terminal, anexos, MCP, extensões
IDE_MASTERY_QUESTIONS: list[dict[str, str]] = [
    {
        "topic": "IDE — Arquitetura geral",
        "question": (
            "Desenhe a arquitetura de uma IDE web completa (React + FastAPI) com: "
            "explorer de arquivos, editor Monaco, terminal PTY, chat IA e painel MCP. "
            "Quais camadas separar e como os módulos se comunicam?"
        ),
        "answer": (
            "Frontend: shell layout + FileTree + Monaco + xterm.js + Chat + ExtensionHost. "
            "Backend: API REST (CRUD workspace), WebSocket (terminal stream + chat + theater), "
            "services/ (filesystem, pty, llm, mcp). Domínio isolado de transporte. "
            "Event bus interno ou mensagens WS tipadas. Nunca lógica de negócio no handler WS."
        ),
    },
    {
        "topic": "IDE — Explorer e workspace",
        "question": (
            "Como implementar explorer de arquivos com abertura de workspace local, "
            "watch de mudanças e lazy-loading de pastas grandes sem travar a UI?"
        ),
        "answer": (
            "API list_dir paginada; virtualização na árvore (react-window); "
            "WebSocket ou SSE para file watcher; debounce de reindex; "
            "caminhos sempre validados contra jail do workspace (path traversal). "
            "Estado: workspace root + expanded nodes em Zustand/Context."
        ),
    },
    {
        "topic": "IDE — Editor de código",
        "question": (
            "Por que Monaco (ou CodeMirror 6) em vez de textarea? "
            "Liste integrações mínimas para uma IDE profissional."
        ),
        "answer": (
            "Monaco: syntax highlight, LSP hooks, minimap, multi-cursor, themes. "
            "Integrar: LSP via language server (pyright, tsserver) em subprocesso; "
            "diagnostics via WebSocket; formatter on save; snippets; "
            "tabs com dirty state e auto-save opcional."
        ),
    },
    {
        "topic": "IDE — Terminal integrado",
        "question": (
            "Explique o fluxo completo: terminal na UI → backend → shell do SO. "
            "Quais bibliotecas e riscos de segurança?"
        ),
        "answer": (
            "Frontend xterm.js; WS bidirecional; backend spawn PTY (pywinpty no Windows, pty no Linux) "
            "ou socket para container. Mensagens: resize cols/rows, stdin, stdout stream. "
            "Riscos: command injection, escape do workspace — whitelist cwd, timeout, sem shell root. "
            "Alternativa: terminal só no workspace path com usuário restrito."
        ),
    },
    {
        "topic": "IDE — Anexos e upload",
        "question": (
            "Como permitir anexar arquivos ao chat da IA e ao contexto RAG "
            "sem expor o servidor a uploads maliciosos?"
        ),
        "answer": (
            "Multipart upload com limite de tamanho/MIME whitelist; scan opcional; "
            "salvar em workspace/uploads/<session>; indexar via index_file assíncrono; "
            "referenciar doc_ids no prompt. Nunca executar binários uploadados. "
            "UI: drag-drop + preview; mostrar hash e tamanho."
        ),
    },
    {
        "topic": "IDE — MCP e agentes",
        "question": (
            "Como a IDE expõe servidores MCP ao agente (Ravenna) e lista tools no UI "
            "sem duplicar a config do Cursor?"
        ),
        "answer": (
            "Painel MCP lê mcp.json do workspace + user; spawn stdio servers como subprocessos; "
            "registry de tools com schema JSON; Agent orchestrator chama tools via mesmo protocolo. "
            "Status: running/stopped/error; logs por servidor. "
            "Reutilizar learning_agent.mcp_server como servidor embutido."
        ),
    },
    {
        "topic": "IDE — Chat + contexto",
        "question": (
            "Como o chat da IDE monta contexto (arquivo aberto, seleção, terminal output, notas RAG) "
            "sem estourar a janela do LLM?"
        ),
        "answer": (
            "Context packer com prioridade: seleção ativa > arquivo aberto > search_knowledge > "
            "terminal últimas N linhas. Truncar por token budget; resumir arquivos grandes via map-reduce. "
            "Fast path para saudações; cache de embeddings por sessão."
        ),
    },
    {
        "topic": "IDE — Extensões e plugins",
        "question": (
            "Qual modelo de extensão permite adicionar painéis, commands e themes "
            "sem recompilar a IDE?"
        ),
        "answer": (
            "Extension manifest (JSON): contributes.commands, views, themes; "
            "host carrega iframe sandboxed ou ESM dinâmico com API limitada (postMessage). "
            "VS Code pattern: activationEvents. Versionar API; permissões por extensão."
        ),
    },
    {
        "topic": "IDE — Git integrado",
        "question": (
            "Como integrar status git, diff inline e commit na IDE web com backend Python?"
        ),
        "answer": (
            "GitPython ou subprocess git -C <workspace>; endpoints /git/status, /diff, /commit; "
            "UI: gutter decorations no Monaco via diff API; "
            "nunca passar flags arbitrários do usuário ao shell — usar lista de subcomandos permitidos."
        ),
    },
    {
        "topic": "IDE — Testes e qualidade",
        "question": (
            "Defina pirâmide de testes para validar que a Ravenna consegue evoluir a IDE: "
            "quais camadas e ferramentas?"
        ),
        "answer": (
            "Unit: Vitest (components), pytest (services). Integration: API + WS com cliente fake. "
            "E2E: Playwright (abrir arquivo, terminal, chat, upload). "
            "Contract: schemathesis OpenAPI. Provas reais: run_proofs após cada entrega."
        ),
    },
    {
        "topic": "IDE — Segurança",
        "question": (
            "Liste 5 controles obrigatórios antes de expor terminal + filesystem + LLM na mesma IDE."
        ),
        "answer": (
            "1) Workspace jail path. 2) Auth sessão/JWT. 3) Rate limit API/WS. "
            "4) CORS restrito. 5) Audit log de comandos terminal e tools MCP. "
            "Opcional: sandbox container por sessão."
        ),
    },
    {
        "topic": "IDE — Performance e escala",
        "question": (
            "A IDE trava com repositórios grandes. Quais otimizações no index RAG, "
            "file tree e WebSocket?"
        ),
        "answer": (
            "Index incremental por hash mtime; fila de background jobs; "
            "Chroma sharding ou limite por workspace; "
            "WS backpressure e chunking; desligar index em node_modules via SKIP_DIRS; "
            "lazy load Monaco até aba ativa."
        ),
    },
    {
        "topic": "IDE — Roadmap Ravenna",
        "question": (
            "Ordene em 6 fases o caminho do MVP atual (chat + neural core) até IDE completa "
            "com terminal e anexos. Justifique cada fase."
        ),
        "answer": (
            "1) Layout shell + tabs. 2) File explorer + Monaco read/write. "
            "3) Terminal PTY via WS. 4) Upload/anexos + RAG. "
            "5) MCP panel + LSP básico. 6) Extensões + Git + CI e2e. "
            "Cada fase entrega valor testável e provas reais."
        ),
    },
]


def create_ide_mastery_quiz() -> dict[str, Any]:
    """Cria todos os quizzes complexos de IDE completa (spaced repetition)."""
    db.init_db()
    now = db._utcnow()
    created: list[dict[str, Any]] = []

    with db.get_connection() as conn:
        for item in IDE_MASTERY_QUESTIONS:
            cursor = conn.execute(
                """
                INSERT INTO quiz_items (topic, question, answer, next_review, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (item["topic"], item["question"], item["answer"], now, now),
            )
            created.append(
                {
                    "id": cursor.lastrowid,
                    "topic": item["topic"],
                    "question": item["question"],
                }
            )

    return {
        "topic": "IDE completa — maestria Ravenna",
        "total": len(created),
        "questions": created,
        "goal": (
            "Validar capacidade de estruturar IDE com explorer, editor, terminal, "
            "anexos, MCP, extensões e Git."
        ),
    }


def get_due_ide_quizzes(limit: int = 5) -> list[dict[str, Any]]:
    """Quizzes de IDE pendentes para revisão."""
    db.init_db()
    now = db._utcnow()
    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, question, next_review
            FROM quiz_items
            WHERE topic LIKE 'IDE —%'
            AND next_review <= ?
            ORDER BY next_review ASC LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    return [dict(r) for r in rows]
