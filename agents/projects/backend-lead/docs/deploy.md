# Ravenna API — deploy local

## Run

```powershell
cd learning-agent
.\scripts\start-api.ps1
```

## Env

- `RAG_DISABLE_CHROMA=true` (Windows estável)
- `API_HOST=127.0.0.1` · `API_PORT=8000`

## Health check

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Esperado: `status: ok`

## IDE

Frontend: `.\scripts\start-ide.ps1` → http://localhost:5173
