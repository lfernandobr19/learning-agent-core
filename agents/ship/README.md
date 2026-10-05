# Ship — integração no repositório

**Ship** = entregar no git. Pode ser **autônomo** (sem 2 h/dia manuais).

## Modos

| Modo | Comando | Você precisa fazer algo? |
|------|---------|--------------------------|
| **Ship autônomo** | `.\scripts\run-operating-loop.ps1 -ShipAuto` | Não — pytest + commit |
| **Pós-train** | `.\scripts\run-operating-loop.ps1 -Train` | Só túnel Vast |
| **Ship manual** | Cursor + `ship_mark_done` | Só itens `autonomous: false` |

## Ship autônomo — como funciona

1. Work order em `agents/ship/queue/` com:
   ```yaml
   autonomous: true
   ship_handler: verify_and_commit   # ou llm_then_verify
   tests:
     - tests/test_backend_probes.py
   files_touch:
     - caminho/do/arquivo
   ```
2. Runner roda pytest → `git add` → `git commit` → move para `done/`

## Segurança

- `AUTO_SHIP_ENABLED=false` desliga tudo
- `AUTO_SHIP_DRY_RUN=true` simula sem commit
- `AUTO_SHIP_LLM=false` bloqueia geração LLM
- **Não faz push** por padrão antigo — agora **`auto_push: true`** em `operating_mode.yaml`
- Push para `origin/<branch-atual>` após commit (desligar: `AUTO_SHIP_PUSH=false`)
- Requer `git remote add origin <url>` configurado
- Itens grandes: use `autonomous: false` + revisão humana

## Prove / Train

```powershell
.\scripts\run-operating-loop.ps1 -ShipAuto
.\scripts\run-operating-loop.ps1 -Prove
.\scripts\run-operating-loop.ps1 -Train
```

## Marcar item manualmente (opcional)

```powershell
python -m learning_agent.scripts.ship_mark_done --id SHIP-XXX --commit abc1234
```
