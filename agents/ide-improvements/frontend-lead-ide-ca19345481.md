# Melhorias IDE — Frontend Lead

**ID:** ide-ca19345481
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
Aqui estão algumas melhorias concretas que podem ser feitas no código e na interface do usuário da Ravenna IDE, focando em acessibilidade, responsividade e performance:

### 1. Acessibilidade - Adicionar rótulos e descrições para elementos de interface

**Problema**: O componente `BottomPanelRegion` não possui rótulos ou descrições para os botões de navegação entre as abas.

**Solução**: Adicione atributos `aria-label` e `aria-describedby` aos elementos de navegação para melhorar a acessibilidade.

**Arquivo alvo**: `ravenna-ide/frontend/src/components/BottomPanelRegion.tsx`

```typescript
const TABS: { id: BottomPanelTab; label: string }[] = [
  { id: 'terminal', label: 'Terminal' },
  { id: 'problems', label: 'Problems' },
  { id: 'output', label: 'Output' },
  { id: 'debug', label: 'Debug Console' },
];

export const BottomPanelRegion: React.FC<BottomPanelRegionProps> = ({ activeTab, open, onTabChange, onClose }) => {
  return (
    <div>
      {TABS.map((tab) => (
        <button
          key={tab.id}
          aria-label={`${tab.label} tab`}
          aria-describedby={`description-${tab.id}`}
          onClick={() => onTabChange(tab.id)}
          className={`tab ${activeTab === tab.id ? 'active' : ''}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
};
```

**Como testar**: Use uma ferramenta de inspeção de acessibilidade (como o Chrome DevTools) para verificar os atributos `aria-label` e `aria-describedby`.

### 2. Responsividade - Melhorar a disposição de painéis laterais

**Problema**: Os painéis laterais (`AgentProgressDashboard`, `AgentsPanel`) não se adaptam bem em dispositivos móveis ou telas menores.

**Solução**: Adicione classes CSS para garantir que os painéis sejam responsivos e se ajustem corretamente em diferentes tamanhos de tela.

**Arquivo alvo**: `ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx`

```typescript
const

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/BottomPanelRegion.tsx