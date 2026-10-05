# Checklist — componentes frontend (RemoteApp IDE)

Antes de dar merge em UI:

- `npx tsc --noEmit` no diretório `ravenna-ide/frontend`
- `npx vitest run` nos testes afetados (ou suite completa se tocou layout global)
- Verificar **a11y**: foco por teclado, labels em inputs, contraste mínimo
- Painéis críticos: Progresso, Destilação, Exames externos
- WebSocket: unsubscribe no cleanup do `useEffect`

## Painéis Ship · Prove · Train

| Componente | Rota API |
|------------|----------|
| AgentProgressDashboard | `/api/agents/progress-dashboard` |
| DistillationPanel | `/api/distillation/status` |
| ExternalExamsPanel | `/api/agents/external-completion` |
