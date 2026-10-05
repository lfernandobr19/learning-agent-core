# Melhorias IDE — Backend Lead

**ID:** ide-c2470c6906
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhoria 1: Adicionar Health Check Endpoint

**Problema:** A aplicação não possui um endpoint de health check, o que dificulta a verificação da saúde do serviço em produção.

**Solução:** Adicionar um endpoint `/health` que responde com status `200 OK` se o serviço estiver funcionando corretamente. Isso facilitará a monitorização e manutenção do sistema.

**Arquivo alvo:** `learning_agent/api.py`

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def health_check():
    return {"status": "OK"}

# Adicione a rota ao FastAPI app
app.include_router(router)
```

**Como testar:** 
1. Inicie o servidor com `uvicorn learning_agent.api:app --reload`.
2. Faça uma requisição GET para `http://localhost:8000/health` e verifique se a resposta é `{"status": "OK"}`.

### Melhoria 2: Implementar WebSocket Autonomia

**Problema:** O código atual não possui implementação de WebSocket para comunicação bidirecional com o cliente, o que pode ser benéfico para aplicações interativas e em tempo real.

**Solução:** Adicionar uma rota WebSocket no `api.py` para receber e enviar mensagens em tempo real. 

**Arquivo alvo:** `learning_agent/api.py`

```python
from fastapi import WebSocket

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # Processar a mensagem recebida e responder
        response_data = f"Echo from server: {data}"
        await websocket.send_text(response_data)
```

**Como testar:** 
1. Inicie o servidor com `uvicorn learning_agent.api:app --reload`.
2. Use um cliente WebSocket para se conectar a `ws://localhost:8000/ws` e enviar mensagens, verificando que as respostas são recebidas corretamente.

### Melhoria 3: Melhorar Autenticação e Autorização

**Problema:** O código atual não possui mecanismos de autenticação ou autorização, o que

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts