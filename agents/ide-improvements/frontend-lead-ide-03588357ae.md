# Melhorias IDE — Frontend Lead

**ID:** ide-03588357ae
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
### Melhoria 1: Ajuste de Layout e Responsividade do `AgentProgressDashboard`

**Problema:** O componente `SparkLine` dentro de `AgentProgressDashboard` não é responsivo. Isso pode causar problemas na exibição em diferentes tamanhos de tela, especialmente dispositivos móveis.

**Solução:** Utilize o hook `useMediaQuery` para determinar o tamanho da tela e ajustar a largura (`width`) e altura (`height`) do gráfico com base no tamanho da tela. Adicione um estilo CSS condicional para garantir que o componente seja responsivo.

**Arquivo Alvo:** 
- **ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx**

```typescript
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import useMediaQuery from '@mui/material/useMediaQuery';

const SparkLine: React.FC<SparkProps> = ({ data }) => {
  const isSmallScreen = useMediaQuery('(max-width:768px)');
  
  return (
    <div style={{
      width: isSmallScreen ? '100%' : 280,
      height: isSmallScreen ? 40 : 56
    }}>
      {/* Componente SparkLine */}
    </div>
  );
};
```

**Como Testar:** Ajuste o tamanho da janela do navegador para menos de 768px e observe se a linha de dados é ajustada corretamente. Verifique também em dispositivos móveis.

### Melhoria 2: Adicionar Tema Escuro ao `AgentsPanel`

**Problema:** O painel atualmente não suporta um tema escuro, o que pode ser difícil para usuários com sensibilidade à luz ou preferência por temas escuros.

**Solução:** Implemente uma opção de tema escuro no componente `AgentsPanel`. Utilize a API do sistema (`window.matchMedia`) para detectar se o modo escuro está ativado e adicionar estilos condicionais.

**Arquivo Alvo:**
- **ravenna-ide/frontend/src/components/AgentsPanel.tsx**

```typescript
import React, { useCallback, useEffect, useState } from 'react';

const AgentsPanel = ({ embedded, onOpenObserver }) => {
  const [isDarkMode, setIsDarkMode] = useState

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentProgressDashboard.tsx
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/BottomPanelRegion.tsx