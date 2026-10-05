# Melhorias IDE — Backend Lead

**ID:** ide-b365dbd944
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhoria 1: Adicionar Health Checks ao Serviço REST

**Problema:** Não há verificações de saúde (health checks) configuradas para o serviço REST, o que pode dificultar a monitorização do estado do sistema.

**Solução:** Adicione um endpoint `/health` que retorne o status do servidor e outros serviços dependentes como banco de dados.

**Arquivo Alvo:**
- `learning_agent/api.py`

**Como Testar:**
1. Inicie o serviço.
2. Acesse `http://localhost:<port>/health` (substitua `<port>` pela porta em que a API está rodando).
3. Verifique se a resposta indica que todos os serviços estão funcionando corretamente.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    # Aqui você pode adicionar verificações de saúde para o banco de dados, cache ou outros serviços.
    return {"status": "OK"}
```

### Melhoria 2: Implementar Autenticação para Endpoints REST

**Problema:** Os endpoints REST não possuem autenticação, o que pode expor a API a acessos não autorizados.

**Solução:** Adicione autenticação básica usando tokens JWT (JSON Web Tokens) para proteger os endpoints sensíveis.

**Arquivo Alvo:**
- `learning_agent/api.py`

**Como Testar:**
1. Configure a autenticação e inicie o serviço.
2. Tente acessar um endpoint protegido sem token de autenticação.
3. Verifique se é retornado um erro 401 (Unauthorized).
4. Acesse o mesmo endpoint com um token válido.

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.get("/protected")
async def protected_route(token: str = Depends(oauth2_scheme)):
    # Aqui você pode verificar o token e retornar os dados protegidos.
    return {"message": "This is a protected route"}
```

### Melhoria 3: Adicionar Suporte para WebSocket

**Problema:** O código atual não possui suporte para comunicação via WebSocket, o que limita a interatividade em tempo

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts