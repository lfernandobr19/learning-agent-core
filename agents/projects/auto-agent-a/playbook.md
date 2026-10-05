# Playbook — Auto Agent A

Agente: `auto-agent-a` | Arquétipo: `backend`

## Missão

APIs

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
| `.cursor/agents/auto-agent-a.md` | Definição delegável no Cursor |
| `.cursor/skills/auto-agent-a-learning/SKILL.md` | Loop de aprendizado |
