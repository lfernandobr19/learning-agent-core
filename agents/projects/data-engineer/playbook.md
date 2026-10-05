# Playbook — Data Engineer

Agente: `data-engineer` | Arquétipo: `data`

## Missão

SQL, ChromaDB, pipelines Python e métricas

## Escopo

Dados, ETL, análise, pipelines, SQL e machine learning aplicado

## Domínios cobertos

- SQL, modelagem e consultas analíticas
- ETL, limpeza e validação de dados
- Pipelines Python e orquestração
- Vector stores, RAG e embeddings (ChromaDB)
- Métricas, agregações e relatórios
- Exportação, sync e governança de dados

## Fluxo padrão

- Entenda fonte, schema e qualidade dos dados
- Valide amostras antes de processar volume completo
- Documente transformações e suposições
- Teste pipelines com dados de exemplo reproduzíveis
- Registre schemas e decisões de modelagem em nota de aprendizado

## Critérios de qualidade

- Queries ou scripts executados com saída verificada
- prove_python_code para transformações críticas
- Contagens e amostras conferidas após ETL


## Evolução do playbook

Quando este agente descobrir padrões novos, a Ravenna ou o próprio agente deve:

1. Atualizar este playbook com a seção nova
2. Registrar em `add_learning_note` com tag `data, sql, etl, rag, analytics`
3. Opcionalmente criar quiz para consolidar

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `manifest.yaml` | Metadados, arquétipo e config de aprendizado |
| `playbook.md` | Este arquivo — fluxos e domínio |
| `.cursor/agents/data-engineer.md` | Definição delegável no Cursor |
| `.cursor/skills/data-engineer-learning/SKILL.md` | Loop de aprendizado |

## Práticas autônomas (atualizado)

- Índices SQLite em `db.init_db`: `idx_notes_*`, `idx_quiz_*`, `idx_agent_*`
- Sprint real: `test_sprint_data_engineer_core.py` verifica índices no `sqlite_master`
- Tags `agent:{slug}` em notas para métricas de evolução L5
- Export fine-tune só após consolidação (`scheduled_consolidation`)
- Peer insights indexados por `from_agent` para playbooks
