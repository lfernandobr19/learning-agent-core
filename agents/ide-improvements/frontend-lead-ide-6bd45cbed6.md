# Melhorias IDE — Frontend Lead

**ID:** ide-6bd45cbed6
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
### Problema de Acessibilidade em AgentsPanel.tsx e ChatInputBar.tsx
**Solução Concreta:** Adicionar `aria` atributos para indicar a funcionalidade do componente, especialmente na interface AgentesPanel onde os usuários podem precisarem entender o que cada tipo de arquetipo significa e em ChatInputBar para fornecer notificação ao usar teclado ou leitores de tela.

**Arquivo alvo:** `AgentsPanel.tsx` e `ChatInputBar.tsx`  
**Como testar a solução:** Utilize ferramentas online como Axe para verificação automatizada, bem como simular diferentes tipos de usuários com deficiência visual ou auditiva que utilizam tecnologias assistivas (telescópio ocular, leitores de tela).

### Problema Performance no ChatInputBar.tsx
**Solução Concreta:** Optimize o manejo da entrada do usuário para evitar re-renderizações desnecessárias e melhorias na chamada `onChange` que não altera os dados, utilizando a função `useCallback`.

**Arquivo alvo:** `ChatInputBar.tsx`  
**Como testar a solução:** Utilize benchmarks de performance e simulações para medir o impacto da otimização sobre os tempos de renderização do componente na interface gráfica, utilizando ferramentas como Lighthouse ou WebPageTest.

### Problema Legibilidade no AgentsPanel.tsx (Textos e Nomeações)
**Solução Concreta:** Aprimorar a legibilidade dos textos nas listagens de agentes, utilizando cores diferentes para cada tipo de arquetipo conforme definido em `ARCHETYPE_LABELS` e adicionando legendas simples explicativas sobre o que representa cada label.

**Arquivo alvo:** `AgentsPanel.tsx`  
**Como testar a solução:

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/ChatInputBar.tsx
- ravenna-ide/frontend/src/components/ChatPanel.tsx