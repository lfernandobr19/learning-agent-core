# Melhorias IDE — Backend Lead

**ID:** ide-12720ddea3
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhoria 1: Adicionar Health Checks para endpoints REST

**Problema:** A aplicação atual não possui uma rota de health check, o que dificulta a monitorização da saúde do serviço.

**Solução:** Adicionar um endpoint de health check simples que retorna status HTTP 200 quando o serviço estiver operacional.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def health_check():
    return {"status": "OK"}
```

**Como Testar:**
- Inicie o servidor com `uvicorn learning_agent.api:app --reload`
- Acesse a rota de saúde através do browser ou curl: `curl http://localhost:8000/health`
- Verifique se a resposta é `{ "status": "OK" }`

### Melhoria 2: Otimizar Performance dos Endpoints REST

**Problema:** Os endpoints atuais podem não estar otimizados para lidar com requisições em alta frequência.

**Solução:** Adicionar middleware de cache para respostas frequentemente solicitadas e usar o FastAPI's `Depends` para gerenciar dependências eficientemente.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import Depends, HTTPException, Request

@app.get("/cached-endpoint")
async def cached_endpoint(request: Request, cache=Depends(cache_dependency)):
    if not cache:
        raise HTTPException(status_code=404, detail="Item not found in cache")

    return {"data": cache.data}
```

**Como Testar:**
- Inicie o servidor com `uvicorn learning_agent.api:app --reload`
- Acesse a rota através do browser ou curl: `curl http://localhost:8000/cached-endpoint`
- Verifique se as respostas estão sendo retornadas mais rapidamente.

### Melhoria 3: Adicionar Automação de WebSocket para Otimizar Autonomia

**Problema:** As WebSockets atuais podem não estar otimizadas para manter a autonomia do sistema, especialmente em casos de falhas ou desconexões.

**Solução:** Implementar uma automação que monitoriza a conexão da WebSocket

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts