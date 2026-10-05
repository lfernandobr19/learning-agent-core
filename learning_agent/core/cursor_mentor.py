"""Cursor como mentor — lições por agente para destilação e evolução L6."""

from __future__ import annotations

from typing import Any

from learning_agent.core import agent_collaboration, distillation, knowledge

# Lições do mentor Cursor (conteúdo rico) — foco em decisão e engenharia real
CURSOR_MENTOR_LESSONS: dict[str, dict[str, str]] = {
    "backend-lead": {
        "decision": """## Mentor Cursor — Backend Lead (decisão)

Cenário: API FastAPI com autonomia asyncio vs Celery.

### Framework de decisão
1. Liste stakeholders e SLI afetados (latência p95, erro rate).
2. Compare 3 opções com prós/contras explícitos.
3. Escolha UMA rota com critérios de sucesso mensuráveis.
4. Defina rollback e observabilidade antes do merge.

### Decisão modelo
Manter asyncio no processo FastAPI enquanto ciclos < 5min e CPU < 70%.
Migrar para Celery quando: tarefas > 2min, fila > 100 jobs, ou falhas OOM.

### Critérios de aceite
- proof_gate verde após mudança
- TestClient cobre rotas de autonomia
- Métrica p95 documentada no runbook""",
        "knowledge": """## FastAPI production — mentor Cursor

Router fino → Service (regras) → Repository (I/O).
async só em I/O; CPU-bound em threadpool.
Transação por request; idempotência em POST críticos.
TestClient + mocks no service layer.""",
        "reasoning": """## API lenta SQLite+Chroma — mentor Cursor

1. **Medir**: p95 por rota, N+1 queries, count() Chroma em hot path.
2. **Priorizar**: cache leitura → paralelizar I/O (asyncio.gather) → índices SQLite.
3. **Mitigar**: debounce index RAG; lazy count Chroma; connection pool.
4. **Aceite**: p95 < 500ms no health; pytest smoke < 30s.
5. **Rollback**: feature flag desliga RAG em rotas críticas.""",
    },
    "frontend-lead": {
        "knowledge": """## React performance — mentor Cursor

useMemo/useCallback só em listas >100 itens ou deps caras.
Virtualize listas longas (react-window).
WS: dedupe por msg_id; cleanup on unmount.
Vitest + Testing Library; evitar snapshot frágil.""",
        "decision": """## Mentor Cursor — Frontend (decisão)

Cenário: LSP Monaco vs Command Palette primeiro.

### Decisão
Command Palette primeiro — menor risco, valida arquitetura de comandos, desbloqueia QA.
LSP depois, com contrato de capabilities documentado.

### Critérios
- Vitest cobre palette + atalhos
- INP < 200ms no fluxo crítico
- Checklist a11y antes do merge""",
        "reasoning": """## Diagnóstico WS duplicado — mentor Cursor

1. Verificar StrictMode double-mount em dev.
2. Auditar handlers onmessage — dedupe por msg_id.
3. Revisar reconexão — não re-subscribe sem cleanup.
4. Teste e2e com Playwright reproduzindo duplicação.""",
    },
    "qa-guardian": {
        "decision": """## Mentor Cursor — QA (decisão)

Cenário: mais agent_sprints vs endurecer peer_quiz.

### Decisão
Endurecer peer_quiz com avaliação real PRIMEIRO — eleva qualidade do que já existe.
Depois agent_sprints curados (1 por domínio/semana).

### Critérios
- Quiz exige evidência (link teste/log)
- Falha < 80% abre weak_area_drill automático
- Smoke obrigatório no CI""",
        "knowledge": """## Pirâmide neste monorepo — mentor Cursor

Unit: pytest learning_agent, Vitest components.
Integração: API + SQLite fixture, sem rede externa.
E2E: Playwright fluxos críticos IDE (chat, explorer).
Flaky: quarentena com ticket, max 2 retries e2e.""",
        "reasoning": """## cloud_sync drift 1 nota — mentor Cursor

1. **Causas**: debounce AUTO_SYNC, rede, timestamp conflito, batch sem push.
2. **Ordem**: health.cloud_sync → audit log SQLite → retry fila.
3. **Aceite**: drift ≤1 nota/24h com alerta; zero perda após closure.
4. **Rollback**: last-write-wins com backup local; reindex idempotente.""",
    },
    "data-engineer": {
        "knowledge": """## SQLite + RAG — mentor Cursor

Índices: quiz_attempts(agent, created_at), agent_exchanges(thread_id).
Chroma: reindex idempotente; fonte de verdade SQLite.
ETL: debounce sync; métrica drift no /health.
Backup antes de delete_collection.""",
        "decision": """## Mentor Cursor — Data (decisão)

Cenário: sync push antes de proof_gate vs tolerância de drift.

### Decisão
Tolerância configurável de drift (ex.: 1 nota/24h) COM alerta — não bloquear proof_gate.
Push sync obrigatório apenas em closures e distilação batch.

### Critérios
- AUTO_SYNC_DEBOUNCE respeitado
- Métrica drift no health endpoint
- Reindex RAG idempotente com backup""",
        "reasoning": """## Notas locais > nuvem — mentor Cursor

Causas: debounce, falha rede, conflito timestamp, AUTO_SYNC off em batch.
Mitigação: fila retry, last-write-wins com audit log, health.cloud_sync_configured.""",
    },
    "finance-lead": {
        "knowledge": """## Mentor Cursor — Finance Lead (conhecimento)

### Fundamentos PF (Brasil)
- **Reserva de emergência**: 6–12 meses de custo fixo em liquidez diária (Selic/Tesouro Selic).
- **Juros compostos**: VP/FV, taxa real = (1+nominal)/(1+inflação)-1.
- **Perfil de risco**: capacidade (horizonte, renda) vs tolerância (sono à noite) — documentar por escrito.

### Mercados
- **Ações B3**: P/L, P/VP, ROE, dívida/EBITDA; setores cíclicos vs defensivos.
- **FIIs**: P/VP, vacância, duration contratos, segmento (logística, shoppings, papel).
- **ETFs**: IVVB11 (S&P proxy), BOVA11 (Ibovespa), custo TER, tracking error.
- **Renda fixa**: Selic, IPCA+, prefixado — marcação a mercado e IR (tabela regressiva RF / 20% ações day trade).

### USD / internacional
- Exposição cambial como risco; hedge parcial via ativos dolarizados ou caixa USD.
- ETFs US via BDR/ETF local até corretora internacional habilitada.

### Compliance PF
- Sem promessa de retorno; sem gestão de terceiros; IR e DARF — confirmar com contador.""",
        "reasoning": """## Mentor Cursor — Finance Lead (raciocínio)

Cenário: IPCA acelera, Selic estável, Ibovespa -15% YTD, USD/BRL +8%.

### Ordem de análise
1. **Macro**: inflação real, política fiscal, fluxo estrangeiro, juros real ex-ante.
2. **Carteira**: concentração setorial, duration RF, beta vs Ibovespa, caixa %.
3. **Cenários**: base / otimista / stress (Selic +200bp, BRL +10%).
4. **Ações possíveis**: rebalancear (não market timing), aumentar RF IPCA+, reduzir alavancagem.

### Heurísticas
- Correlação sobe em crises — diversificação geográfica reduz risco idiossincrático, não sistêmico.
- Drawdown >20% no índice: revisar tese por ativo, não panic sell sem critério pré-definido.
- Backtest ≠ futuro — usar para sizing e stress, não para prometer retorno.

### Saída esperada
3 drivers macro + 2 riscos de carteira + 1 ação de rebalanceamento com gatilho mensurável.""",
        "decision": """## Mentor Cursor — Finance Lead (decisão L6)

Cenário: você tem R$ 50k, reserva ok, horizonte 10 anos, tolerância moderada.
Oportunidade: concentrar 40% em 2 ações de tech BR após queda de 30%.

### Framework L6
1. **Trade-offs**: concentração vs diversificação; recuperação histórica vs risco de permanente impairment.
2. **Decisão UMA rota** (exemplo): máx 15% por emissor / 25% por setor; entrada em tranches (3 meses).
3. **Critérios mensuráveis**: P/L < mediana setor; dívida líquida/EBITDA < 3; stop de revisão se drawdown posição >25%.
4. **Rollback**: se tese invalidada (queda receita 2 trimestres), reduzir 50% posição.
5. **Prova**: journal + planilha sizing; paper trade 30 dias antes de ordem real.

### Paper trading only
Registrar ordem simulada, slippage 0,1%, comparar vs benchmark (BOVA11 + CDI blend).

### Fora de escopo
Captação, recomendação a terceiros, alavancagem sem margem documentada.""",
    },
    "reliability-lead": {
        "decision": """## Mentor Cursor — Reliability (decisão)

Cenário: incidente P2 — latência p95 3x em produção.

### Decisão em 15 min
1. Rollback deploy se mudança < 2h (feature flag kill switch).
2. Senão: scale horizontal + investigar dependência externa.
3. Comunicar status page; postmortem em 48h.

### Critérios
- Runbook linkado no alerta
- Trace_id em toda rota crítica
- SLO budget documentado""",
        "knowledge": """## Observabilidade — mentor Cursor

Logs JSON com correlation-id.
Métricas RED: rate, errors, duration por rota.
Health: liveness vs readiness separados.
Alertas acionáveis — sem página sem runbook.""",
        "reasoning": """## p95 triplicou pós-deploy — mentor Cursor

1. **Correlacionar**: deploy diff, trace_id, dependência externa, GC/OOM.
2. **Priorizar**: rollback se release <2h; senão scale + profile CPU.
3. **Aceite**: p95 volta ao SLO em 30min; erro rate < 1%.
4. **Rollback**: feature flag kill switch documentado no runbook.""",
    },
}

PEER_STUDY_PAIRS: list[tuple[str, str, str]] = [
    ("data-engineer", "backend-lead", "contratos API + persistência"),
    ("reliability-lead", "qa-guardian", "SLOs e critérios de merge"),
    ("frontend-lead", "qa-guardian", "a11y + testes e2e"),
    ("finance-lead", "data-engineer", "métricas Sharpe, backtest e pipelines de dados"),
]


def run_cursor_mentor_session(
    agent: str,
    dimension: str = "decision",
    *,
    sync_cloud: bool = False,
    distill: bool = True,
) -> dict[str, Any]:
    """Mentor Cursor destila lição focada na dimensão fraca do agente."""
    slug = agent.strip().lower().replace("_", "-")
    manifest = agent_collaboration._load_manifest(slug) or {}
    display = manifest.get("display_name", slug)
    lessons = CURSOR_MENTOR_LESSONS.get(slug, {})
    content = lessons.get(dimension) or lessons.get("decision", "")
    if not content:
        content = (
            f"## Mentor Cursor — {display}\n\n"
            f"Dimensão: {dimension}. Decisão com trade-offs, critérios de aceite e provas verdes."
        )

    import os

    title = f"[Cursor Mentor/{dimension}] {display}"
    skip_distill = (
        not distill
        or os.environ.get("EVOLUTION_SKIP_DISTILL", "").lower() in {"1", "true", "yes", "on"}
    )
    if skip_distill:
        note = knowledge.add_note(
            title,
            f"**Mentor:** Cursor (tier Sonnet/Opus)\n**Dimensão:** {dimension}\n\n{content[:2500]}",
            tags=["cursor-mentor", f"agent:{slug}", "l6-refinement"],
            sync_cloud=sync_cloud,
        )
        row = {"success": True, "skipped_distill": True, "note_id": note.get("note_id"), "topic": title}
    else:
        row = distillation.distill_from_teacher_content(
            title,
            content,
            source_ref="cursor-mentor",
            teacher_model=f"cursor-mentor-{slug}",
            tags=["cursor-mentor", f"agent:{slug}", f"dimension:{dimension}", "l6-refinement"],
            sync_cloud=sync_cloud,
        )
        knowledge.add_note(
            title,
            f"**Mentor:** Cursor (tier Sonnet/Opus)\n**Dimensão:** {dimension}\n\n{content[:2500]}",
            tags=["cursor-mentor", f"agent:{slug}", "l6-refinement"],
            sync_cloud=sync_cloud,
        )
    return {
        "success": True,
        "action": "cursor_mentor_session",
        "agent": slug,
        "dimension": dimension,
        "distillation": row,
    }


def run_peer_study_round(agent: str) -> dict[str, Any]:
    """Agente estuda com par — troca via peer_question."""
    from learning_agent.core import agent_autonomy

    slug = agent.strip().lower().replace("_", "-")
    pair = next((p for p in PEER_STUDY_PAIRS if p[0] == slug or p[1] == slug), None)
    if not pair:
        return {"success": False, "error": f"sem par de estudo para {slug}"}

    topic = pair[2]
    return agent_autonomy.execute_autonomy_action("peer_question", topic=f"{topic} ({slug})")
