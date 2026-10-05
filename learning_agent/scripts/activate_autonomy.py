"""Ativa autonomia always-on e opcionalmente dispara primeiro ciclo."""

from __future__ import annotations

import asyncio
import sys

from learning_agent.core import agent_autonomy, agent_factory


def _ensure_core_agents() -> None:
    listing = agent_factory.list_agents()
    projects = listing.get("projects", [])
    if len(projects) >= 2:
        return
    from learning_agent.scripts.scaffold_core_agents import main as scaffold_core

    scaffold_core()


async def main() -> None:
    _ensure_core_agents()
    result = await agent_autonomy.set_always_on(True, interval_seconds=300)
    print("always_on:", result.get("always_on"))
    print("running:", result.get("status", {}).get("running"))
    print("actions:", len(agent_autonomy.AUTONOMY_ACTIONS))
    if not result.get("success"):
        print("error:", result.get("error"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
