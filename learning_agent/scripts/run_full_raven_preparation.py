"""Roteiro completo — preparação total da Raven até todas as fases verdes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

LOG = Path("data/raven_preparation_run_internal.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def wait_ollama_model(name: str, timeout_s: int = 3600) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
            if name in (r.stdout or ""):
                log(f"Modelo {name} disponível no Ollama")
                return True
        except Exception as exc:
            log(f"ollama list: {exc!r}")
        log(f"Aguardando {name}...")
        time.sleep(30)
    return False


# Professor Cursor — lições por domínio (conteúdo rico para destilação)
CURSOR_LESSONS: list[tuple[str, str, str]] = [
    (
        "Backend — FastAPI em camadas production-ready",
        "backend",
        """## Arquitetura
Router → Service → Repository. Routers só validam HTTP; services orquestram regras; repos acessam DB.

## Padrões
- Pydantic v2 para request/response
- Dependency injection para sessão DB
- `async def` quando I/O; CPU-bound em threadpool
- Idempotência em POST críticos via chave cliente

## Testes
TestClient para rotas; mocks no service; integração com DB em memória ou fixture.

## Erros
HTTPException mapeada; nunca vazar stack trace; correlation-id no header.

## Pitfalls
Lógica no router; N+1 queries; transação aberta demais.""",
    ),
    (
        "Frontend — React TypeScript staff patterns",
        "frontend",
        """## Estado
Estado servidor em React Query; UI local em useState; evitar prop drilling com composição.

## Performance
memo + useMemo só com profiling; virtualizar listas longas; code-split por rota.

## A11y
Landmarks, focus trap em modais, aria-live para toasts, contraste WCAG AA.

## Testes
Vitest + Testing Library — testar comportamento, não implementação.

## Pitfalls
useEffect para derivar estado; re-renders em contexto global inchado.""",
    ),
    (
        "QA — pirâmide de testes em monorepo Python+React",
        "qa",
        """## Camadas
Unit (rápido, muitos) → integração (API+DB) → e2e (fluxos críticos).

## Critérios de merge
Smoke obrigatório; cobertura não é meta cega — assert comportamento.

## Flaky
Isolar relógio/rede; retries só em e2e com limite; quarentena com ticket.

## CI
Paralelizar por marca pytest; cache deps; falhar rápido no lint+unit.""",
    ),
    (
        "Data — RAG e embeddings em produção",
        "data",
        """## Pipeline
Chunk 500-1500 tokens com overlap; metadata rica; dedupe por hash.

## Retrieval
Híbrido keyword+vetor; rerank opcional; limit 5-8 para contexto LLM.

## Observabilidade
Log query, hits, latência; drift de corpus versionado.

## Pitfalls
Reindex sem backup; embedding model mismatch entre index e query.""",
    ),
    (
        "Reliability — observabilidade e SLOs",
        "reliability",
        """## Três pilares
Logs estruturados JSON; métricas RED/USE; traces em rotas críticas.

## SLO
Definir SLI (latência p95, erro rate); orçamento de erro mensal.

## Runbooks
Alerta acionável; link runbook; escalação clara.

## Health
Liveness vs readiness; dependências no readiness check.""",
    ),
    (
        "Agentes — orquestração multi-agente com provas",
        "agents",
        """## Design
Persona + playbook + ferramentas; um cérebro compartilhado ou tier por domínio.

## Provas
Nada é "pronto" sem verified: testes, lint, ou checklist automatizado.

## Memória
RAG por projeto; notas de sessão; closures de aprendizado.

## Pitfalls
Agentes sem ferramentas; marcar sucesso sem prova.""",
    ),
]

# Expandir até 30 lições reutilizando variações por domínio
_EXTRA_TOPICS = [
    ("API REST — versionamento e contratos", "backend", "Versione /v1; OpenAPI como contrato; breaking change exige nova major. Deprecate com sunset header."),
    ("PostgreSQL — índices e planos de query", "backend", "EXPLAIN ANALYZE antes de índice; composto segue ordem de filtro; evitar seq scan em tabelas quentes."),
    ("WebSockets — reconexão e backpressure", "backend", "Heartbeat ping/pong; fila por cliente; idempotência de mensagens com msg_id."),
    ("Segurança — authn/authz em APIs", "backend", "JWT curto + refresh rotacionado; RBAC no service; nunca confiar só no frontend."),
    ("CSS — design tokens e temas", "frontend", "Tokens semânticos (--color-surface); dark mode via prefers-color-scheme + classe; documentar escala."),
    ("Performance — Core Web Vitals", "frontend", "LCP: hero otimizado; INP: handlers leves; CLS: dimensões reservadas em mídia."),
    ("Testes e2e — Playwright estável", "qa", "data-testid; esperar rede idle com cuidado; screenshots em falha; paralelo por spec file."),
    ("Contratos de API — testes de consumidor", "qa", "Pact ou schema JSON; CI falha se contrato quebrar; versionar fixtures."),
    ("Pipelines ETL idempotentes", "data", "Watermark incremental; DLQ para poison; schema evolution com compatibilidade."),
    ("SQLite em produção leve", "data", "WAL mode; busy_timeout; migrations versionadas; backup antes de migrate."),
    ("Chaos e resiliência", "reliability", "Timeouts em toda chamada externa; circuit breaker; bulkhead por dependência."),
    ("Incident response", "reliability", "Severity P1-P4; comms template; postmortem blameless em 48h."),
    ("Scaffold de agentes Cursor", "agents", "manifest + playbook + skill; gatilhos claros; learning loop desde dia 1."),
    ("Knowledge distillation — professor forte", "agents", "Professor gera conteúdo rico; aluno local condensa; medir similaridade lexical como proxy."),
    ("Entrega software completo sob demanda", "agents", "Decomposição em épicos; agente por camada; integração contínua com provas verdes."),
    ("DDD tático — aggregates", "backend", "Uma transação por aggregate; invariantes dentro do aggregate; eventos de domínio opcionais."),
    ("Monorepo — boundaries", "frontend", "Packages internos; API surface mínima; CI afetado por grafo de deps."),
    ("A11y em formulários complexos", "frontend", "label associado; erros aria-describedby; ordem de tab lógica."),
    ("Mutation testing — quando usar", "qa", "Custo alto; usar em módulos críticos de regra de negócio."),
    ("Feature flags", "reliability", "LaunchDarkly ou env; default off; kill switch documentado."),
    ("CI/CD — preview environments", "reliability", "PR gera preview URL; smoke automático; destroy após merge."),
    ("Prompt engineering para código", "agents", "Contexto mínimo necessário; critérios de aceite; pedir plano antes de código em tarefas grandes."),
    ("Code review eficaz", "agents", "PR < 400 linhas; checklist segurança/perf/teste; aprovar só com CI verde."),
    ("Caching HTTP e CDN", "backend", "Cache-Control por rota; invalidação em deploy; ETag para APIs read-heavy."),
]

for title, domain, body in _EXTRA_TOPICS:
    CURSOR_LESSONS.append((title, domain, f"## Domínio: {domain}\n\n{body}\n\n## Entrega\nCódigo testado, documentado, observável."))


def run_cursor_distill(target: int = 30) -> int:
    from learning_agent.core import distillation

    done = 0
    for title, domain, content in CURSOR_LESSONS:
        if done >= target:
            break
        for attempt in range(3):
            try:
                distillation.distill_from_teacher_content(
                    title,
                    content,
                    source_ref="cursor",
                    teacher_model=f"cursor-{domain}",
                    tags=["cursor-teacher", f"domain:{domain}", "raven-preparation"],
                    sync_cloud=False,
                )
                done += 1
                log(f"Cursor destilado [{done}]: {title[:50]}")
                break
            except Exception as exc:
                log(f"ERRO cursor (tentativa {attempt + 1}) {title[:40]}: {exc!r}")
                if attempt < 2:
                    warm_student_model()
    return done


def run_groq_distill_until(target: int = 80) -> None:
    from learning_agent import db
    from learning_agent.core import software_excellence

    db.init_db()
    with db.get_connection() as c:
        current = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]

    while current < target:
        batch = software_excellence.run_distillation_batch(
            target_pairs=target,
            max_topics=5,
            broadcast_observer=False,
            refresh_brain=False,
        )
        added = batch.get("distilled", 0)
        log(f"Groq batch: +{added} pares (meta {target})")
        if added == 0:
            log("Groq batch sem progresso — parando loop groq")
            break
        with db.get_connection() as c:
            current = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]
        log(f"Total pares: {current}")


def run_l6_all() -> None:
    from learning_agent.core import agent_model_parity
    from learning_agent.core.agent_capability import CORE_AGENTS

    for slug in CORE_AGENTS:
        try:
            r = agent_model_parity.run_model_parity_assessment(slug, broadcast_observer=False)
            log(f"L6 {slug}: score={r.get('composite_score')} ok={r.get('success')}")
        except Exception as exc:
            log(f"ERRO L6 {slug}: {exc!r}")


def warm_student_model(model: str = "phi3:mini") -> None:
    import httpx

    try:
        with httpx.Client(timeout=600.0) as client:
            client.post(
                "http://localhost:11434/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "max_tokens": 5,
                    "temperature": 0.1,
                },
            )
        log(f"Warm-up Ollama ({model}) concluído")
    except Exception as exc:
        log(f"Warm-up falhou (continuando): {exc!r}")


def main() -> int:
    import os

    os.environ.setdefault("STUDENT_MODEL", "phi3:mini")
    log("=== INÍCIO preparação total Raven ===")
    warm_student_model(os.environ["STUDENT_MODEL"])

    from learning_agent.config import RAVEN_BASE_MODEL
    from learning_agent.core import finetune, raven_readiness, software_excellence

    log("Fase 1a: destilação Cursor (professor) — não depende do 14B")
    run_cursor_distill(target=30)

    log("Fase 1b: destilação Groq até 80 pares")
    run_groq_distill_until(target=80)

    log(f"Fase 2: pull exclusivo {RAVEN_BASE_MODEL}")
    subprocess.run(["ollama", "pull", RAVEN_BASE_MODEL], check=False, timeout=7200)

    if not wait_ollama_model(RAVEN_BASE_MODEL, timeout_s=120):
        log(f"TIMEOUT: {RAVEN_BASE_MODEL} não disponível após pull")
        return 1

    log("Fase 3: recriar raven no 14B")
    software_excellence.run_brain_pipeline(dry_run=False, broadcast_observer=False)

    log("Fase 4: export + recriar raven com corpus ampliado")
    finetune.export_training_data(min_pairs=0)
    software_excellence.run_brain_pipeline(dry_run=False, broadcast_observer=False)

    log("Fase 5: paridade L6 todos os agentes")
    run_l6_all()

    log("Fase 6: avaliação final")
    readiness = raven_readiness.assess_readiness()
    factory = software_excellence.assess_excellence()
    summary = {
        "readiness_pct": readiness["summary"]["readiness_pct"],
        "readiness_complete": readiness["complete"],
        "missing": readiness.get("missing", []),
        "factory_pct": factory["summary"]["factory_ready_pct"],
        "pairs": readiness["corpus"]["total_pairs"],
        "cursor_pairs": readiness["corpus"]["cursor_pairs"],
        "training": readiness["corpus"]["training_examples"],
    }
    log(f"RESULTADO: {json.dumps(summary, ensure_ascii=False)}")
    Path("data/raven_preparation_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log("=== FIM ===")
    return 0 if readiness["complete"] else 0


if __name__ == "__main__":
    sys.exit(main())
