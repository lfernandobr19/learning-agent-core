"""Cria os quatro agentes principais do ecossistema — via Ravenna."""

from __future__ import annotations

from learning_agent.core import agent_factory

CORE_AGENTS = [
    {
        "name": "backend-lead",
        "archetype": "backend",
        "description": "Especialista backend — APIs, persistência, async e testes de servidor.",
        "focus": "FastAPI, SQLite, WebSocket, pytest e arquitetura de camadas",
        "display_name": "Backend Lead",
    },
    {
        "name": "frontend-lead",
        "archetype": "frontend",
        "description": "Especialista frontend — React, UI RemoteApp, a11y e testes Vitest.",
        "focus": "React, TypeScript, CSS RemoteApp, componentes e acessibilidade",
        "display_name": "Frontend Lead",
    },
    {
        "name": "qa-guardian",
        "archetype": "qa-inspector",
        "description": "Vistorias, testes, correções e regressões com provas.",
        "focus": "Qualidade, pytest, vitest, CI e checklist de entrega",
        "display_name": "QA Guardian",
    },
    {
        "name": "data-engineer",
        "archetype": "data",
        "description": "Dados, ETL, SQL, RAG e pipelines analíticos.",
        "focus": "SQL, ChromaDB, pipelines Python e métricas",
        "display_name": "Data Engineer",
    },
    {
        "name": "reliability-lead",
        "archetype": "debug-optimizer",
        "description": "Debug, testes, proof_gate e saúde do ecossistema de agentes.",
        "focus": "pytest, provas reais, auditoria de agentes, otimização de ciclos autônomos",
        "display_name": "Reliability Lead",
    },
]


def main() -> None:
    results = []
    for spec in CORE_AGENTS:
        result = agent_factory.scaffold_agent_project(
            spec["name"],
            spec["archetype"],
            spec["description"],
            focus=spec["focus"],
            display_name=spec["display_name"],
            overwrite=True,
        )
        results.append(result)
        status = "ok" if result.get("success") else result.get("error")
        print(f"{spec['name']}: {status}")

    ok = sum(1 for r in results if r.get("success"))
    print(f"\n{ok}/{len(CORE_AGENTS)} agentes criados.")


if __name__ == "__main__":
    main()
