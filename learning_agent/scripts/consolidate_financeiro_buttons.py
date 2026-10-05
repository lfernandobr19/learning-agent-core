#!/usr/bin/env python3
"""Consolida diagnóstico Financeiro PWA — botões não respondem."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent.core import knowledge, theater  # noqa: E402
from learning_agent.core.supervision_agents import SupervisionContext, broadcast_supervision_round  # noqa: E402

BODY = """# Consolidação — Financeiro PWA (botões não respondem)

**Data:** {date}

## Conectividade GitHub (Ravenna)
- Workspace `financeiro` anexado: `data/external-repos/financeiro`
- Remoto: `https://github.com/BigXandi/Financeiro.git` (git clone OK)
- App publicado: `https://bigxandi.github.io/Financeiro/`

## Diagnóstico autônomo Ravenna
- Work order recebida; resposta **não executou** leitura real de arquivos
- Alucinação: citou `assets/index.html` (index está na raiz)
- Listou comandos shell sem usar ferramentas de workspace

## Causa raiz (Cursor)
Quando `assets/app.js` **não carrega** (abrir `index.html` solto, PWA/SW com cache quebrado, pasta incompleta), o `#splash` fica em `z-index: 9999` e bloqueia todos os cliques. A UI aparece por baixo mas nada responde.

Quando JS carrega: botões funcionam (validado em GitHub Pages — FAB, nav, modal).

## Patch mínimo aplicado (workspace financeiro)
1. `index.html` — fallback 5s + `onerror` no script com toast
2. `app.js` — `boot()` em try/catch/finally (sempre esconde splash)
3. `styles.css` — splash hidden com `visibility: hidden`
4. `sw.js` — `CACHE_NAME` → v2.2.1

## Lição para Ravenna (debug PWA)
1. Confirmar estrutura real (`index.html` na raiz, não em assets/)
2. Usar API workspace / leitura de arquivos — não inventar `ls`/`cat`
3. Testar cenários: HTTPS vs file:// vs PWA instalada
4. Verificar se `#splash` ainda intercepta cliques (DevTools → pointer-events)

## Próximo passo humano
- Publicar patch no repo BigXandi/Financeiro (push + Pages)
- Usuário: limpar cache PWA / reinstalar atalho na tela inicial
- Informar onde abriu o app (Pages, arquivo local, PWA)
"""


async def _broadcast(role: str, agent: str, content: str, *, level: str = "") -> None:
    await theater.post_agent_message(role, agent, content, level=level)
    await theater._pause(0.25)


async def main() -> int:
    level = "Financeiro — diagnóstico PWA"
    note = knowledge.add_note(
        "[Financeiro] Botões bloqueados — splash + JS não carregado",
        BODY.format(date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        tags=["financeiro", "pwa", "debug", "ravenna-ide", "consolidacao", "github"],
    )
    note_id = note.get("note_id") or note.get("id")

    await broadcast_supervision_round(
        SupervisionContext(
            level=level,
            topic="Financeiro PWA — splash bloqueando cliques",
            process="consolidation",
            mentor_directive=(
                f"Ravenna: nota #{note_id}. Em bugs de UI PWA, sempre verifique se app.js carregou "
                "e se #splash foi removido. Use workspace financeiro — não invente paths."
            ),
            reviewer_focus="Validar patch no GitHub Pages após push; pedir cenário do usuário (file vs HTTPS).",
            extra={"note_id": note_id},
        ),
        broadcast=_broadcast,
        pause_seconds=0.28,
    )

    await _broadcast(
        "ravenna",
        "Ravenna",
        f"Consolidei diagnóstico Financeiro: splash bloqueia cliques se JS falhar. Patch no workspace. Nota #{note_id}.",
        level=level,
    )
    print(f"consolidated note_id={note_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
