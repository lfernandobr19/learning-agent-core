"""Prática real finance-lead — foco reasoning (L6 operacional).

Uso local (VM ou PC com venv):
  python -m learning_agent.scripts.run_finance_reasoning_practice

Modo remoto (PC → API VM):
  python -m learning_agent.scripts.run_finance_reasoning_practice --api http://ravenna-vm:8000
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Prática real finance-lead — reasoning")
    parser.add_argument(
        "--api",
        default=os.environ.get("RAVENNA_API_BASE", "").strip(),
        help="Base URL da API (ex.: http://ravenna-vm:8000). Vazio = execução local.",
    )
    args = parser.parse_args()

    if args.api:
        base = args.api.rstrip("/")
        with httpx.Client(timeout=3600.0) as client:
            r = client.post(f"{base}/api/agents/finance-lead/reasoning-practice")
            r.raise_for_status()
            result = r.json()
    else:
        from learning_agent.core import finance_lead_engine

        result = finance_lead_engine.run_reasoning_practice_session()

    print(json.dumps(result, ensure_ascii=False, indent=2)[:8000])
    rb = result.get("reasoning_before")
    ra = result.get("reasoning_after")
    print(f"\nreasoning: {rb} → {ra} | L6 operacional: {result.get('l6_operational')}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
