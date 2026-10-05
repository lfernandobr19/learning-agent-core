# Melhorias IDE — Backend Lead

**ID:** ide-7e6c2f2a3a
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhorias Propostas para a Ravenna IDE

#### 1. Implementar Health Checks Endpoints REST
**Problema:** O código atual não possui endpoints de health checks, tornando difícil monitorar o status da aplicação em tempo real.

**Solução:** Adicionar um endpoint `/health` que responda com um status HTTP `200 OK` se tudo estiver funcionando corretamente. Este endpoint pode ser expandido para incluir verificações mais detalhadas, como a saúde do banco de dados ou outros serviços dependentes.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    # Aqui você pode implementar verificações mais detalhadas, como checar o banco de dados.
    return {"status": "OK"}
```

**Como Testar:** Acesse `http://localhost:8000/health` (ou a porta correta configurada) e verifique que o endpoint retorna um JSON com `"status": "OK"`.

#### 2. Implementar Autenticação em Endpoints REST
**Problema:** Os endpoints REST atuais não têm autenticação, permitindo acesso não autorizado à aplicação.

**Solução:** Adicionar uma camada de autenticação básica usando JWT (JSON Web Tokens) para proteger os endpoints importantes.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, "SECRET_KEY", algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Could not validate credentials",
                                headers={"WWW-Authenticate": "Bearer"})
    except jwt.JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Could not validate credentials",
                            headers={"WWW-Authenticate": "Bearer"})

@app.get("/protected")
async def protected_route(current_user: str = Depends(get

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts