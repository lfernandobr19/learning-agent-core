"""Destilação em massa — corpus do cérebro Ravenna."""

from __future__ import annotations

import argparse
import json
import sys

from learning_agent.core import software_excellence


def main() -> int:
    parser = argparse.ArgumentParser(description="Destilação em massa para fábrica de software")
    parser.add_argument("--target", type=int, default=20, help="Pares mínimos no corpus")
    parser.add_argument("--max-topics", type=int, default=None, help="Limite de tópicos nesta execução")
    parser.add_argument("--no-brain", action="store_true", help="Não recriar o modelo raven após batch")
    args = parser.parse_args()

    result = software_excellence.run_distillation_batch(
        target_pairs=args.target,
        max_topics=args.max_topics,
        broadcast_observer=False,
        refresh_brain=not args.no_brain,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
