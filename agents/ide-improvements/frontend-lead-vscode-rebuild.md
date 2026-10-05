# Frontend rebuild — Visual Cursor / VS Code

**Agente:** frontend-lead  
**Data:** 2026-06-13  
**Motivação:** Usuário rejeitou visual roxo/neon/starfield; pediu refazer baseado em Cursor e VS Code.

## Decisões

1. **Removido** do shell ativo: `IdeAmbient`, starfield, nebula, animações shimmer, tema RemoteApp.
2. **Novo** `vscode-workbench.css` — tokens Dark+ oficiais (`#1e1e1e`, `#252526`, `#333333`, `#007acc`).
3. **Monaco** volta ao `vs-dark` nativo.
4. **Tipografia** Inter + JetBrains Mono (sem Orbitron/Rajdhani).
5. **Tabs** estilo VS Code — barra superior, borda azul no tab ativo.
6. **Activity bar** — ícone cinza, barra branca à esquerda quando ativo.
7. **Status bar** azul VS Code (`#007acc`).
8. **Explorer** — lista plana, hover `#2a2d2e`, sem glass/violet.

## Arquivos principais

- `ravenna-ide/frontend/src/styles/vscode-workbench.css` (novo)
- `ravenna-ide/frontend/src/styles/globals.css` (limpo)
- `App.tsx`, `TitleBar`, `FileExplorer`, `EditorWorkbench`, `MonacoEditorPane`

## Próximo (frontend-lead)

- [ ] Chat panel estilo Cursor (composer fixo, histórico limpo)
- [ ] Settings como JSON editor com syntax highlight
- [ ] Ícones Codicons (opcional: `@vscode/codicons`)
- [ ] Remover CSS legado `ide-shell.css` / `nucleus.css` se não referenciados

## Como testar

```powershell
cd ravenna-ide\frontend
npm run dev
```

Abrir http://localhost:5173 — deve parecer VS Code Dark+, não “sci-fi roxo”.
