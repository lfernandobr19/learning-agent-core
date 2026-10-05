"""Padrão de entrega equivalente ao Cursor — todos os projetos Ravenna IDE.

Não é sobre visual da IDE: é sobre qualidade de entrega de software —
integrar, validar no ambiente certo, deploy quando aplicável, critério de aceite atendido.
"""

from __future__ import annotations

from typing import Any

CURSOR_EQUIVALENT_DELIVERY_BLOCK = """\
PADRÃO DE ENTREGA (equivalente Cursor — OBRIGATÓRIO em todo projeto Ravenna IDE):

Entrega incompleta = FALHA. Arquivos soltos sem integração NÃO contam.

1. **Integrar** — mudanças entram no fluxo real (entrypoint, rotas, imports, config). Não deixe stubs órfãos.
2. **Validar** — rode o comando de validação do projeto (`npm run build`, `pytest`, etc.) no ambiente correto:
   - Frontend Node: dentro de `frontend/` ou via Docker build, NÃO assuma `npm` no host se não existir.
   - Backend Python: `pytest` / `unittest` no path certo.
3. **Deploy** — se o pedido ou o projeto exige produção (PWA, API, serviço), faça rebuild/restart e confirme URL no ar.
4. **Aceite** — cumpra o critério de aceite literal do pedido antes de declarar DONE.
5. **Aprender** — se falhar: `record_project_lesson` com causa + correção; se passar: o que garantiu entrega completa.

Anti-padrões (reprovam entrega):
- Criar componentes/arquivos que ninguém importa
- Duplicar entrypoints (`App.js` + `App.tsx`, `Layout` em dois lugares)
- Declarar sucesso com build quebrado ou sem deploy pedido
- Desviar para benchmarks/tarefas fora do `projectRoot`
"""


def apply_to_spec(spec: dict[str, Any], *, prompt: str, mode: str = "agent") -> dict[str, Any]:
    if (mode or "").strip().lower() != "agent":
        return spec
    lowered = (prompt or "").lower()
    audit_only = "só diagnóstico" in lowered or "sem write" in lowered or "sem write/patch/shell" in lowered
    if audit_only:
        return spec
    updated = dict(spec)
    updated["cursorEquivalentDelivery"] = True
    return updated


def format_for_prompt(spec: dict[str, Any] | None) -> str:
    if not (spec or {}).get("cursorEquivalentDelivery"):
        return ""
    return CURSOR_EQUIVALENT_DELIVERY_BLOCK


def integration_failures(changed_paths: list[str], *, project_root: str | None) -> list[str]:
    """Heurísticas de entrega incompleta detectáveis sem rodar o app."""
    failures: list[str] = []
    normalized = [p.replace("\\", "/").strip("/") for p in changed_paths]
    orphan_markers = ("AppShell.jsx", "AppShell.tsx", "/theme/tokens.css")
    entry_changed = any(p.endswith(("App.tsx", "App.jsx", "App.js", "main.py", "main.ts")) for p in normalized)
    orphan_only = any(any(m in p for m in orphan_markers) for p in normalized) and not entry_changed
    if orphan_only:
        failures.append(
            "Entrega incompleta: arquivos de design/estrutura alterados sem integrar no entrypoint (App/main)."
        )
    if any(p.endswith("App.js") or p.endswith("App.jsx") for p in normalized):
        if any(p.endswith("App.tsx") for p in normalized):
            failures.append("Entrypoint duplicado: App.js/App.jsx conflita com App.tsx — mantenha só App.tsx.")
        else:
            failures.append(
                "App.js/App.jsx como entry órfão — use App.tsx (Vite/React) ou remova duplicata."
            )
    return failures
