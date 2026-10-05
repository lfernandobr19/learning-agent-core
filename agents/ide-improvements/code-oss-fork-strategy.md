# Fork Code-OSS — decisão 2025-06

## Decisão
**Clone VS Code + AI Ravenna** via fork [Code-OSS](https://github.com/microsoft/vscode) (MIT).

## Entregue nesta sessão
- `ravenna-ide/extensions/ravenna-ai/` — extensão TypeScript (Chat + Composer na secondary sidebar, Ctrl+L)
- `scripts/setup-code-oss-fork.ps1` — clone + merge `product.ravenna.json`
- `scripts/build-ravenna-extensions.ps1` — compila extensões
- `docs/ravenna-code-oss-fork.md` — guia completo
- `ravenna-ide/code-oss/product.ravenna.json` — branding Ravenna IDE
- `ide_objectives.py` — north star atualizado + probe `code_oss_fork`

## Próximo
1. F5 em `ravenna-ai` com API :8000
2. `.\scripts\setup-code-oss-fork.ps1` quando tiver ~15 GB e Build Tools
3. Fase MCP stdio na extensão + Composer com WorkspaceEdit
