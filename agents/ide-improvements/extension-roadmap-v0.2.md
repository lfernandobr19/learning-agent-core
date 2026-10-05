# Roadmap extensão Ravenna AI — VS Code

Estratégia: **VS Code nativo + extensão `ravenna-ai`** = IDE concluída.

## Sprint 1 ✅ (v0.1.0)
- [x] Chat webview + API
- [x] Composer shell
- [x] Activity bar container
- [x] VSIX installável
- [x] Ctrl+L

## Sprint 2 ✅ (v0.2.0)
- [x] Composer `parseFileBlocks` + `applyEditsFromComposer` (WorkspaceEdit local)
- [x] Inline completions via `/api/lsp/completion`
- [x] Painéis: Agents, Observer (teatro), MCP invoke, Rules, Attachments, IDE Progress
- [x] @file contexto do editor ativo
- [x] `ide_objectives.py` — probes aceitam VS Code + extensão (100% paridade estática)
- [x] LICENSE + repository no package.json

## Sprint 3 (opcional — fork Code-OSS)
- [ ] Bundled extension no product.json
- [ ] Secondary sidebar quando VS Code ≥ 1.97
- [ ] MCP stdio spawn nativo na extensão
- [ ] Deprecar `ravenna-ide/frontend` web

## Instalar v0.2.0

```powershell
cd ravenna-ide\extensions\ravenna-ai
npm.cmd run compile
npx.cmd vsce package --no-dependencies --allow-missing-repository
code --install-extension .\ravenna-ai-0.2.0.vsix --force
```

Ou: `powershell -ExecutionPolicy Bypass -File .\scripts\install-ravenna-ai-extension.ps1`

## Painéis (activity bar → Ravenna)

| Aba | Função |
|-----|--------|
| Chat | Conversa + @file |
| Composer | Multi-arquivo + botão Aplicar |
| Agents | Lista agentes da API |
| Observer | Teatro ao vivo |
| MCP | Invocar tools |
| Rules | Rules & skills |
| Attachments | Upload RAG |
| IDE Progress | Paridade % |

## API obrigatória

```powershell
.\.venv312\Scripts\python.exe -m learning_agent.api
```
