"""Project-specific autonomy profiles — evita gates de benchmark (fulfillment) em produtos reais."""

from __future__ import annotations

import re
from typing import Any

_BENCHMARK_SEMANTIC = frozenset(
    {
        "event-sourcing",
        "node-cli-testable",
        "jsonl-line-errors",
        "idempotency",
        "integer-cents",
    }
)

_BENCHMARK_FILE_MARKERS = ("fulfillment", "fixtures/events", "src/cli.js", "billing.js", "cart.js")


def is_ravenna_home_root(project_root: str | None) -> bool:
    root = (project_root or "").replace("\\", "/").strip("/").lower()
    return root == "ravenna-home" or root.startswith("ravenna-home/")


def apply_profile(spec: dict[str, Any], *, project_root: str | None, prompt: str) -> dict[str, Any]:
    if not is_ravenna_home_root(project_root):
        return spec
    return _apply_ravenna_home_profile(dict(spec), project_root=project_root, prompt=prompt)


def _apply_ravenna_home_profile(spec: dict[str, Any], *, project_root: str | None, prompt: str) -> dict[str, Any]:
    root = (project_root or spec.get("projectRoot") or "ravenna-home").replace("\\", "/").strip("/")
    lowered = (prompt or "").lower()
    frontend_only = root.endswith("/frontend") or (
        "frontend" in lowered and "backend" not in lowered and "pytest" not in lowered
    )

    spec["ravennaHome"] = True
    spec["projectRoot"] = "ravenna-home/frontend" if frontend_only else root
    spec["semanticRules"] = [r for r in (spec.get("semanticRules") or []) if r not in _BENCHMARK_SEMANTIC]

    deploy_markers = (
        "rh-07",
        "rh-08",
        "rh-09",
        "voz",
        "voice",
        "microfone",
        "instalar app",
        "pwa install",
        "gates duros",
        "barra equivalente cursor",
        "deploy obrigatório",
        "deploy obrigatorio",
        "ui pro",
        "3 abas",
        "2 abas",
        "abas clicáveis",
        "abas clicaveis",
        "full-screen",
        "full screen",
        "espaço",
        "espaco",
        "neon",
    )
    if frontend_only and any(marker in lowered for marker in deploy_markers):
        spec["ravennaHomeDeploy"] = True
        spec["ravennaHomeRequireDeploy"] = True
        spec["ravennaHomeRemoteValidation"] = True
        spec["ravennaHomePreclean"] = True

    if frontend_only:
        spec["enforceAllowedPaths"] = True

    shell_cmds = list(spec.get("validationCommands") or [])
    build_cmd = "npm run build" if spec["projectRoot"].endswith("/frontend") else "cd frontend && npm run build"
    if spec.get("ravennaHomeDeploy"):
        from learning_agent.core.ravenna_home_remote_ops import BUILD_CMD, UP_CMD

        shell_cmds = [BUILD_CMD, UP_CMD]
    elif frontend_only or not shell_cmds:
        shell_cmds = [c for c in shell_cmds if "npm run build" in c] or [build_cmd]
    if spec.get("ravennaHomeUiMode") == "voice-pwa":
        shell_cmds = [c for c in shell_cmds if "pytest" not in c]
    elif "backend" in lowered or "pytest" in lowered:
        if "py -m pytest" not in " ".join(shell_cmds):
            shell_cmds.append("py -m pytest backend/tests -q")
    spec["validationCommands"] = list(dict.fromkeys(shell_cmds))

    required = [
        path
        for path in (spec.get("requiredFiles") or [])
        if not any(marker in path.replace("\\", "/").lower() for marker in _BENCHMARK_FILE_MARKERS)
    ]
    if frontend_only:
        required = [
            path
            for path in required
            if path.replace("\\", "/").startswith(("frontend/", "src/", "components/", "theme/"))
            or "/" not in path.replace("\\", "/")
        ]
    spec["requiredFiles"] = required
    from learning_agent.core import ravenna_home_delivery

    spec = ravenna_home_delivery.apply_ui_mode(spec, prompt=prompt)
    if not spec.get("allowedPaths"):
        spec["allowedPaths"] = [
            "src",
            "theme",
            "index.html",
            "public",
            "vite.config.ts",
        ]
        if not frontend_only:
            spec["allowedPaths"].extend(["backend/main.py", "backend/tests"])
    spec["lockedFiles"] = list(dict.fromkeys([*(spec.get("lockedFiles") or []), "package.json"]))
    if spec.get("ravennaHomeLockApp"):
        spec["lockedFiles"].append("src/App.tsx")
    if spec.get("ravennaHomeLockChat"):
        spec["lockedFiles"].append("src/components/Chat.tsx")
    if spec.get("ravennaHomeLockCss"):
        spec["lockedFiles"].extend(["src/index.css", "theme/tokens.css", "frontend/src/index.css"])
    if spec.get("ravennaHomeLockMain"):
        spec["lockedFiles"].extend(["main.py", "backend/main.py"])
    spec["forbiddenPaths"] = [
        "package.json",
        "frontend/package.json",
        "src/fulfillment.js",
        "test/fulfillment.test.mjs",
        "fixtures/events.jsonl",
        "src/App.js",
        "src/App.jsx",
    ]
    return spec


def repair_rules_block(spec: dict[str, Any] | None) -> str:
    if (spec or {}).get("ravennaHome"):
        deploy = (spec or {}).get("ravennaHomeDeploy")
        validation_hint = (
            "- Build/deploy rodam via SSH no host VM (docker compose ravenna-home-web) — "
            "NÃO use `npm`/`node` no shell; foque em integrar `App.tsx`.\n"
            "- Layout em `src/Layout.tsx` (`import Layout from './Layout'`), nunca `components/Layout`.\n"
        ) if deploy else (
            "- Valide com docker compose build ravenna-home-web no host VM quando aplicável.\n"
        )
        return (
            "Regras obrigatórias para Ravenna Home (PWA React/Vite):\n"
            "- Trabalhe SOMENTE em `ravenna-home/frontend/src/` e `frontend/theme/`.\n"
            "- PROIBIDO criar `App.js` ou `App.jsx` — somente `App.tsx`.\n"
            "- PROIBIDO sobrescrever ou editar `package.json` — build quebra (JSON estrito).\n"
            "- PROIBIDO criar ou editar benchmarks Node ou arquivos fora de `ravenna-home/`.\n"
            "- Integre mudanças em `App.tsx` com abas `useState` (Chat | Casa).\n"
            f"{validation_hint}"
            "- Retorne blocos ```write``` ou ```patch``` completos para os arquivos alterados."
        )
    return (
        "Regras obrigatórias para projetos Node.js sem dependências externas:\n"
        "- Se usar node --test, importe `test` de `node:test` e `assert` de `node:assert/strict`; não use describe/it/expect de Jest.\n"
        "- CLI ESM deve detectar execução direta com `fileURLToPath(import.meta.url)`.\n"
        "- Billing/finance deve usar centavos inteiros, arredondamento explícito, totalizadores e ledger.\n"
        "- Se `npm test` roda 0 testes, isso é FALHA: crie testes reais.\n"
        "- Retorne todos os arquivos faltantes/corrigidos em blocos ```write``` completos."
    )


def mentions_fulfillment_benchmark(text: str) -> bool:
    for line in (text or "").splitlines():
        ll = line.lower()
        if not re.search(r"\bfulfillment\b", ll) and "event-sourced" not in ll and "event sourced" not in ll:
            continue
        if any(
            neg in ll
            for neg in (
                "não desvie",
                "fora do escopo",
                "proibido",
                "ex.:",
                "ex:",
                "não altere",
                "apagar",
                "remov",
                "benchmark",
                "outro projeto",
            )
        ):
            continue
        return True
    return bool(re.search(r"\breplayevents\b", (text or "").lower()))
