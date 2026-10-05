# Melhorias IDE — Frontend Lead

**ID:** ide-1c404a7131
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
### Melhoria 1: Acessibilidade e Responsividade no `AgentProgressDashboard.tsx`

**Problema:**  
O componente `SparkLine` não possui nenhuma propriedade relacionada à acessibilidade, como rótulos de texto para os valores do gráfico. Além disso, a largura fixa (`width = 280`) pode não se adequar bem em dispositivos móveis.

**Solução:**  
Adicionar um atributo `aria-label` para fornecer descrições acessíveis e tornar a largura responsiva.

**Arquivo Alvo:**  
`ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx`

**Código Alterado:**
```tsx
const SparkLine: React.FC<SparkProps> = ({
  data,
  width = '100%', // Tornar a largura responsiva
  height = 56,
}) => {
  const ariaLabel = `Gráfico de progresso com valores ${data.join(', ')}`;
  
  return (
    <div style={{ width, height }} aria-label={ariaLabel}>
      {/* Código do gráfico */}
    </div>
  );
};
```

**Como Testar:**  
- Use um leitor de tela para verificar se a descrição acessível está correta.
- Verifique o comportamento em diferentes tamanhos de janela e dispositivos móveis.

### Melhoria 2: Acessibilidade no `AgentsPanel.tsx`

**Problema:**  
As labels das arquétipos (`ARCHETYPE_LABELS`) não são fornecidas com atributos de acessibilidade, o que pode dificultar a navegação para usuários dependentes de leitores de tela.

**Solução:**  
Adicionar `aria-label` ou `aria-labelledby` aos elementos que exibem essas labels.

**Arquivo Alvo:**  
`ravenna-ide/frontend/src/components/AgentsPanel.tsx`

**Código Alterado:**
```tsx
const renderArchetypeLabel = (archetype: string) => (
  <span aria-label={ARCHETYPE_LABELS[archetype]}>{ARCHETYPE_LABELS[archetype]}</span>
);
```

**Como Testar:**  
- Use um leitor de tela para verificar se a descrição acessível está correta.
- Verifique visualmente se as labels estão

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/BottomPanelRegion.tsx