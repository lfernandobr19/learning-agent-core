# Melhorias IDE — Frontend Lead

**ID:** ide-6e58474525
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
Aqui estão algumas melhorias concretas que podem ser implementadas no código/UI da Ravenna IDE, focando em acessibilidade, responsividade e legibilidade:

### 1. Adicionar Atributos de Acessibilidade ao `SparkLine`

**Problema:** O componente `SparkLine` não possui atributos de acessibilidade, o que pode dificultar a navegação para usuários com deficiência visual.

**Solução:** Adicione os atributos `aria-label`, `role="img"` e `tabIndex="-1"` ao elemento SVG do `SparkLine`.

**Arquivo Alvo:** `ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx`

```typescript
const SparkLine: React.FC<SparkProps> = ({
  data,
  width = 280,
  height = 56,
}) => {
  return (
    <svg role="img" aria-label={`Gráfico de linhas com dados ${data.join(', ')}`} tabIndex="-1">
      {/* Renderização das linhas */}
    </svg>
  );
};
```

**Como Testar:** Use um leitor de tela (como o NVDA) para verificar se a descrição do gráfico é lida corretamente.

### 2. Melhorar Legibilidade no `BottomPanelRegion`

**Problema:** O painel inferior (`BottomPanelRegion`) pode ter problemas de legibilidade, especialmente quando usado em dispositivos com baixa resolução ou contraste insuficiente.

**Solução:** Adicione estilos para garantir que o texto e os botões tenham um bom contraste e tamanho adequado. Use variáveis CSS para facilitar a manutenção.

**Arquivo Alvo:** `ravenna-ide/frontend/src/components/BottomPanelRegion.tsx`

```typescript
const BottomPanelRegion: React.FC<BottomPanelRegionProps> = ({ activeTab, open, onTabChange, onClose }) => {
  return (
    <div className="bottom-panel-region">
      {/* Outros elementos */}
      {TABS.map(tab => (
        <button key={tab.id} onClick={() => onTabChange(tab.id)} className={`tab ${activeTab === tab.id ? 'active' : ''}`}>
          {tab.label}
        </button>
      ))}
    </div>
  );
};

// CSS
.bottom-panel-region {

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/BottomPanelRegion.tsx