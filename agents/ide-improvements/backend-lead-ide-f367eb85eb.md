# Melhorias IDE — Backend Lead

**ID:** ide-f367eb85eb
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhoria 1: Adicionar health checks para endpoints REST

**Problema:** A aplicação não possui rotas de saúde, o que dificulta a monitoração da disponibilidade dos serviços.

**Solução:** Adicionar uma nova rota `/health` que retorna um status HTTP 200 quando todos os serviços estão funcionando corretamente. Isso pode ser feito adicionando uma nova função na classe `FastAPI`.

**Arquivo alvo:** `learning_agent/api.py`

**Como testar:**
1. Execute a aplicação.
2. Acesse `http://localhost:<port>/health` via navegador ou ferramentas como curl ou Postman.
3. Verifique se o status HTTP 200 é retornado.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "OK"}
```

### Melhoria 2: Adicionar CORS middleware para endpoints REST

**Problema:** A aplicação não possui configuração de CORS (Cross-Origin Resource Sharing), o que pode causar problemas de segurança e acesso cruzado entre diferentes origens.

**Solução:** Configurar o CORS no FastAPI permitindo todas as origens, métodos e cabeçalhos para testes. Em produção, essas permissões devem ser ajustadas conforme a necessidade.

**Arquivo alvo:** `learning_agent/api.py`

**Como testar:**
1. Execute a aplicação.
2. Tente realizar uma requisição CORS de um domínio diferente (por exemplo, via POSTMAN).
3. Verifique se a requisição é aceita sem erros.

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Melhoria 3: Implementar WebSocket para comunicação bidirecional

**Problema:** A aplicação não possui suporte a WebSockets, limitando a comunicação em tempo real entre o cliente e o servidor.

**Solução:** Implementar uma nova rota de WebSocket `/ws` que permite a comunicação

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts