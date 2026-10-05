# Melhorias IDE — Backend Lead

**ID:** ide-e57abdbcf6
**Agente:** backend-lead

## Temas
- endpoints REST e performance
- WebSocket theater e autonomia
- health checks e provas

## Proposta
### Melhoria 1: Adicionar Health Checks para endpoints REST

**Problema:** Não há nenhum endpoint de health check na aplicação, o que dificulta verificar se os serviços estão funcionando corretamente.

**Solução:** Adicionar um endpoint `/health` que responde com status `200 OK` caso todos os serviços estejam em execução e com status `500 Internal Server Error` caso contrário. Este endpoint também pode retornar informações mais detalhadas sobre o estado do sistema, como o status da conexão com o banco de dados.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    try:
        # Aqui você pode adicionar lógica para verificar a saúde do sistema, como conexão com o banco de dados.
        db_health = await check_db_connection()  # Supondo que esta função verifica a conexão com o banco de dados
        if not db_health:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Database connection failed"})
        
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
```

**Como Testar:** Inicie a aplicação e faça uma requisição GET para o endpoint `/health` utilizando ferramentas como `curl`, Postman ou Insomnia. Verifique se retorna status 200 com conteúdo `{ "status": "ok" }`.

### Melhoria 2: Adicionar CORS Middleware para endpoints REST

**Problema:** A aplicação não possui nenhum middleware de CORS configurado, o que pode impedir requisições de frontends em diferentes dominios.

**Solução:** Configurar o FastAPI com um middleware de CORS para permitir origens específicas ou todas as origens durante o desenvolvimento.

**Arquivo Alvo:** `learning_agent/api.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Configurando CORS
origins = [
    "http://localhost",
    "http://localhost:3000",  # Exemplo de porta do frontend React

## Arquivos analisados
- learning_agent/api.py
- learning_agent/core/__init__.py
- ravenna-ide/frontend/src/utils/api.ts