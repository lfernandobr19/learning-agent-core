# Playbook — Ravenna IDE Rebuild (Treino L6)

**Projeto:** `ravenna-ide/` · **Duração:** ~1 semana · **Prioridade:** qualidade

## Por que existe

Primeiro **projeto completo** dos agentes após L6 cognitivo. A Raven Eco IDE deixa de ser só "aula" e vira **entrega real** medida por `ide_completion` (22 objetivos must).

## Papéis

| Agente | Papel no IDE |
|---|---|
| **frontend-lead** | Shell, painéis, chat, composer, a11y |
| **backend-lead** | API workspace, LSP, terminal, git, MCP |
| **qa-guardian** | proof_gate, Vitest, regressões |
| **reliability-lead** | debug_sweep, performance, estabilidade |
| **data-engineer** | RAG/anexos, métricas, search |

## Loop obrigatório (cada ação)

```
search_knowledge → implementar → testar → journal → closure
                      ↓ falha
                 record_failure → fix → journal → retomar
```

Implementado em código: `learning_agent/core/agent_action_journal.py`

## Evolução incremental — preservar IDE atual

Trabalhar sempre por mudanças pequenas, revisáveis e reversíveis dentro de `ravenna-ide/`.
É **proibido** remover ou recriar `ravenna-ide/` por completo durante sessões normais do Agent.
Quando uma área estiver ruim, substituir apenas o módulo necessário, preservando arquivos adjacentes,
histórico de usuário e fluxo funcional. Toda mudança deve ter diff claro, validação e plano de rollback.

## Raven motor · Cursor braços

- **Ravenna (MCP/API):** orquestra, prioriza milestone, registra journal
- **Cursor (Task):** braços de construção — edita o **novo** `ravenna-ide/`, terminal, testes até verde (Cursor não é o produto final)
- **Vast 32B:** raciocínio longo nas sessões (não autonomia cega 24/7)

## Referências

- Plano semanal: `week-plan.yaml`
- Objetivos must: `get_ide_completion_status`
- Layout rebuild: workbench VS Code (editor centro, AI direita)

## Encerramento do dia

1. `proof_gate` verde no escopo do dia
2. `record_session` por agente participante
3. Nota `[Treino IDE]` com erros aprendidos
