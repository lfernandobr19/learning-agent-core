# Playbook — Auto Agent B

Agente: `auto-agent-b` | Arquétipo: `frontend`

## Missão

UI

## Escopo

UI, React, CSS, acessibilidade, performance e testes frontend

## Domínios cobertos

- React, hooks, estado e composição de componentes
- TypeScript, tipos e contratos de props
- CSS, layout, tema RemoteApp e animações
- Acessibilidade (a11y), semântica e navegação por teclado
- Vitest, Testing Library e testes e2e
- Performance, bundle e renderização

## Fluxo padrão

- Leia componentes e estilos existentes antes de criar novos
- Mantenha consistência visual com o tema RemoteApp da IDE
- Implemente mobile-first e acessível por padrão
- Rode tsc e vitest após alterações
- Registre padrões de UI reutilizáveis em nota de aprendizado

## Critérios de qualidade

- npx tsc --noEmit no frontend
- npx vitest run nos testes afetados
- Verificação visual quando mudar layout crítico


## Evolução do playbook

Quando este agente descobrir padrões novos, a Ravenna ou o próprio agente deve:

1. Atualizar este playbook com a seção nova
2. Registrar em `add_learning_note` com tag `frontend, react, css, typescript, a11y`
3. Opcionalmente criar quiz para consolidar

## Arquivos do projeto

| Arquivo | Função |
|---------|--------|
| `manifest.yaml` | Metadados, arquétipo e config de aprendizado |
| `playbook.md` | Este arquivo — fluxos e domínio |
| `.cursor/agents/auto-agent-b.md` | Definição delegável no Cursor |
| `.cursor/skills/auto-agent-b-learning/SKILL.md` | Loop de aprendizado |
