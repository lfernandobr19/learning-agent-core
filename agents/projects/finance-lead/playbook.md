# Playbook — Finance Lead

Agente: `finance-lead` | Arquétipo: `custom`

## Missão

Finanças pessoais, mercados BR e USD, gestão de risco e **paper trading** — sempre para **capital próprio**, sem promessa de retorno.

## Escopo

- Macro (Selic, IPCA, Fed, câmbio)
- Ações, FIIs, ETFs (B3 e internacional)
- Risco (drawdown, sizing, stop)
- Backtest e journal de decisões
- Impostos e compliance **pessoa física** (visão educacional — confirmar com contador)

## Fora de escopo

- Captar ou administrar dinheiro de terceiros
- Ordens reais em corretora (até você habilitar explicitamente)
- Promessa de retorno curto

## Fluxo padrão

1. `search_knowledge` — o que já foi estudado
2. Formular tese: premissa → risco → critério de invalidação
3. Paper trade ou backtest antes de qualquer ordem real
4. `add_learning_note` + `record_session` ao encerrar

## Raven motor · Cursor braços

- **Ravenna (API/MCP/Telegram):** orquestra, journal, Prove externo
- **Cursor (mentor estático + proxy Groq):** lições knowledge/reasoning/decision → destilação
- **Web (`search_and_learn`):** pesquisa indexada nos gaps — ciclos ímpares (qualidade)
- **Currículo:** `agents/curricula/finance-lead.yaml` — marcos L2→L6
- **Prática:** backtest reprodutível, journal, drill de decisão
- **Vast 32B:** raciocínio longo no overnight (não autonomia cega 24/7)

MCP: `get_finance_lead_training_status`, `run_finance_lead_quality_cycle`, `get_agent_curriculum`

## Modo operacional (Ship · Prove · Train)

- **Ship** — merge no git (2 h/dia). Fila: `agents/ship/queue/`
- **Prove** — critérios externos `completion-criteria.yaml` + blinds semanais
- **Train** — 1 ciclo/noite Vast, alinhado ao próximo item Ship

Critérios externos: `completion-criteria.yaml` (F1–F5).  
Rodar probes: `pytest tests/test_finance_probes.py -q`

## Sessão noturna (Vast)

Prompts e tópicos: `agents/projects/finance-lead/overnight-prompts.yaml`

```powershell
# Terminal 1 — túnel
.\scripts\vast-overnight-finance.ps1 -TunnelOnly

# Terminal 2 — loop até 06:00
.\scripts\vast-overnight-finance.ps1 -RunOvernight -Until 06:00
```

## Journal obrigatório (qualidade > velocidade)

Toda ação → SQLite `agent_action_log` + nota RAG.  
Todo erro → `record_failure` + correção documentada antes de continuar.

## Formato L6 (decisões)

Trade-offs → **uma** decisão → critérios mensuráveis → rollback → prova (backtest/log).

## Blind exams (Prove cego)

- Cenários: `tests/agent_benchmarks/finance-lead/blind_*.yaml` — limiar **≥80%**
- Respostas: `agents/exams/finance-lead_blind_*.json`
- Prompt compartilhado: `learning_agent/core/finance_blind_exam.py` (`BLIND_EXAM_SYSTEM`)
- Campo **`risk`** obrigatório em português: mencionar **drawdown**, **sizing**, **stop** ou **volatilidade**
- Tickers B3 sem sufixo `.SA` (ex.: `PETR4`, não `PETR4.SA`)

### Automação (A / B / C)

| Opção | Quando | Comando / gatilho |
|-------|--------|-------------------|
| **A** | Dom 09:30 (Task Scheduler) | `run-finance-blind-batch.ps1` → batch 5× + consolidate + Telegram |
| **B** | Overnight ciclo `% 10` | `FINANCE_BLIND_BATCH_EVERY_CYCLES=10` — batch 5× no L6 sprint |
| **C** | Overnight ciclo `% 4` (se não for batch) | `FINANCE_BLIND_FRESH_EVERY_CYCLES=4` — 1 LLM/blind |

Registrar tarefas: `.\scripts\register-scheduled-tasks.ps1`

### Interpretação dos resultados

| Score | Significado | Ação |
|-------|-------------|------|
| 100% | Compliance total na rubrica | Manter; rodar batch mensal |
| 80–99% | Passou, mas gap em critério (ex. risk) | Revisar JSON em `agents/exams/` |
| <80% | Falha — não operar paper | Telegram alerta + `--fresh` no dia |
| σ alto entre runs | Instabilidade do LLM | Reforçar prompt ou baixar temperature |

Backup automático: `data/backups/blind/` a cada batch/fresh. Backup geral: tarefa `Ravenna-LearningAgent-Backup` (Drive 3×/dia).

Revisão humana leve: Telegram `/finance` + olhar 1 decisão pending/semana.

```powershell
python -m learning_agent.scripts.run_finance_blind_exams --batch 5 --alert --consolidate
python -m learning_agent.scripts.run_finance_blind_exams --fresh --alert
python -m learning_agent.scripts.consolidate_finance_blind_session
python -m learning_agent.scripts.run_ravenna_finance_automation_audit
```

## Práticas autônomas (atualizado)

Motor `finance_decision_loop` — ciclo paper **decidir → provar → agir → journal**:

1. Lê `diversified_manifest` + `economic_news_manifest` + `data/market/*.json`
2. Gera decisão L6 (JSON): premissa, tese, risco, invalidação, rollback
3. Valida **F1** (backtest), **F4** (tickers), **F5** (recusa se dados incompletos)
4. Modo **assisted** (default): pending + Telegram `/decision approve|register <id>`
5. Modo **autonomous**: `FINANCE_DECISION_MODE=autonomous` — commit paper após probes OK
6. **`live_orders: false`** — ordens reais só com flag explícita futura

Consolidação Fase 1 (a cada 5 ciclos overnight): SM-2, weak_area_drill, proof_gate, gaps.

```powershell
# Testar decisão manual
python -m learning_agent.scripts.run_finance_decision --dry-run
```

## Diretivas Telegram

- [2026-06-11 20:16] Develop backend integration using Node.js or Python Flask for Telegram Bot and Google Maps API.



- [2026-06-11 20:11] Focus on real-time location data integration and Telegram interaction.
