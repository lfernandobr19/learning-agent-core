"""Marca item Ship como concluído (move queue → done)."""

from __future__ import annotations

import argparse

from learning_agent.core import ship_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Marcar work order Ship como done")
    parser.add_argument("--id", required=True, help="ID ex: SHIP-001")
    parser.add_argument("--commit", default="", help="Hash do commit mergeado")
    args = parser.parse_args()

    result = ship_pipeline.mark_done(args.id, commit=args.commit)
    if not result.get("success"):
        print(f"Erro: {result.get('error')}")
        return 1
    print(f"OK → {result.get('moved_to')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
