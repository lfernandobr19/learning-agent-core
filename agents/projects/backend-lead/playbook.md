# Playbook — Backend Lead

Agente: `backend-lead` | Arquétipo: `backend`

## Missão

FastAPI, SQLite, WebSocket, pytest e arquitetura de camadas

## Escopo

APIs, banco de dados, async, WebSockets, testes e arquitetura de servidor

## Domínios cobertos

- APIs REST e contratos OpenAPI
- FastAPI, middleware, dependências e validação Pydantic
- SQLite, PostgreSQL, migrations e modelagem
- Async, WebSockets e tarefas em background
- Testes pytest, fixtures e integração
- Segurança, auth, rate limiting e observabilidade

## Fluxo padrão

- Entenda requisitos, contratos e limites de performance antes de codar
- Busque padrões existentes no repositório com search_code
- Projete camadas (router → service → repository) com contratos claros
- Implemente com testes e provas reais (prove_python_code, pytest)
- Documente decisões de arquitetura na nota de aprendizado

## Critérios de qualidade

- pytest no módulo alterado
- prove_python_code para snippets críticos
- verified true nas tools antes de considerar pronto


## Evolução do playbook

Quando este agente descobrir padrões novos, a Ravenna ou o próprio agente deve:

1. Atualizar este playbook com a seção nova
2. Registrar em `add_learning_note` com tag `backend, api, fastapi, database, async`
3. Opcionalmente criar quiz para consolidar

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `manifest.yaml` | Metadados, arquétipo e config de aprendizado |
| `playbook.md` | Este arquivo — fluxos e domínio |
| `.cursor/agents/backend-lead.md` | Definição delegável no Cursor |
| `.cursor/skills/backend-lead-learning/SKILL.md` | Loop de aprendizado |

## Práticas autônomas (atualizado)

- Sprint real: `tests/agent_sprints/test_sprint_backend_lead_core.py` valida `/health` via TestClient
- Manter um único `run_server()` em `api.py` — evitar rotas duplicadas
- `learning_closure` avalia quiz por sobreposição de termos, não auto-correct
- Priorizar endpoints `/api/agents/*` com contratos estáveis para a IDE
- Após `debug_sweep`, sincronizar nuvem se drift de notas > 5
