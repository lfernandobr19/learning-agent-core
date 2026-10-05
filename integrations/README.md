# Integração Multi-IDE

O learning-agent funciona em qualquer IDE ou ferramenta que suporte MCP ou HTTP.

## Cursor

Copie o conteúdo de `cursor-mcp.json` para `~/.cursor/mcp.json` (merge com servidores existentes)
ou use o `.cursor/mcp.json` do projeto (já configurado).

## VS Code

MCP nativo no VS Code (GitHub Copilot Agent). Guia completo: [`docs/vscode-mcp-ravenna.md`](../docs/vscode-mcp-ravenna.md)

Resumo:
1. Abra a pasta `learning-agent` como workspace
2. `.vscode/mcp.json` já configura o servidor **ravenna**
3. `Ctrl+Shift+P` → **MCP: List Servers** → **ravenna** → **Start**
4. Chat em modo **Agent** → **Configure Tools** → ative tools da Ravenna

## Claude Desktop

1. Abra `%APPDATA%\Claude\claude_desktop_config.json`
2. Adicione o bloco de `claude-desktop.json` em `mcpServers`

## HTTP (qualquer cliente)

### API REST (porta 8000)

```bash
# Iniciar API
python -m learning_agent.api

# Health check
curl http://127.0.0.1:8000/health

# Buscar conhecimento
curl "http://127.0.0.1:8000/knowledge/search?q=python+decorators"

# Ver progresso
curl http://127.0.0.1:8000/progress
```

### MCP HTTP (porta 8001)

```bash
python -m learning_agent.mcp_server --transport streamable-http --port 8001
```

Clientes MCP que suportam Streamable HTTP podem conectar em `http://127.0.0.1:8001`.

## Scripts e automações

Qualquer linguagem pode consumir a API REST. Exemplo Python:

```python
import httpx

r = httpx.get("http://127.0.0.1:8000/progress")
print(r.json())
```
