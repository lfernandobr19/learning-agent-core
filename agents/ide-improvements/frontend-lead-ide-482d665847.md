# Melhorias IDE — Frontend Lead

**ID:** ide-482d665847
**Agente:** frontend-lead

## Temas
- Observador e painéis laterais
- performance e legibilidade do chat
- acessibilidade e responsividade

## Proposta
**Problema de Performance e Legibilidade do Chat**
Solução: Implementar um mecanismo para filtrar mensagens antigas, permitindo que apenas as últimas `n` (por exemplo, 10) sejam visíveis. Fazer com que a entrada de texto embutida fique responsiva e semântica ao usar o componente `<textarea>` no lugar do elemento `<input>`.
Arquivo alvo: ravenna-ide/frontend/src/components/ChatPanel.tsx
Compara as mensagens atuais com a última `n` (por exemplo, 10) e filtra quaisquer que não sejam recentes usando o estado para armazenar apenas essas últimas `n`.
```typescript
const [recentMessages, setRecentMessages] = useState<Message[]>([])
//... dentro do usoEffect com dependencia de recentMessages e messages:
setRecentMessages(prev => {
  const unshiftedArray = Array.prototype.slice.call(messages).unshift(...recentMessages);
  return unshiftedArray.splice(-10); // Adiciona apenas as últimas 10 mensagens ao estado recente, removendo o restante se for maior que isso.
})
```
Para implementar a entrada filtrável para recentemente enviadas e lidas:
- Coloque um `<textarea>` em vez de um elemento `<input>`. Isso é mais semântico para uma área onde os usuários podem digitar mensagens longas.
```jsx
<textarea onChange={(e) => setChatValue(e.target.value)} value={chatValue} />
```
- Para tornar o componente responsivo, utilize as propriedades `placeholder` e ajuste os estilos conforme necessário para que eles sejam aplicados em diferentes tamanhos de tela.

**Acessibilidade com Responsividade no Painel Agentes**
Solução: Adicionar um botão "Expandir" ou alternar a visibilidade dos painéis laterais para garantir

## Arquivos analisados
- ravenna-ide/frontend/src/components/AgentsPanel.tsx
- ravenna-ide/frontend/src/components/AttachmentsPanel.tsx
- ravenna-ide/frontend/src/components/ChatInputBar.tsx
- ravenna-ide/frontend/src/components/ChatPanel.tsx