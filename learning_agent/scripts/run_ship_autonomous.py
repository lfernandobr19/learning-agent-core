"""CLI — Ship autônomo (testes → commit)."""

from __future__ import annotations

import argparse
import json
import os

from learning_agent.core import ship_autonomous


def main() -> int:
    parser = argparse.ArgumentParser(description="Ship autônomo — pytest + git commit")
    parser.add_argument("--max-items", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--item", default="", help="ID específico ex: SHIP-006")
    args = parser.parse_args()

    os.environ.setdefault("RAG_DISABLE_CHROMA", "true")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

    if args.item:
        from learning_agent.core import ship_pipeline

        item = next((q for q in ship_pipeline.list_queue() if q.get("id") == args.item), None)
        if not item:
            print(json.dumps({"success": False, "error": "item não encontrado"}, ensure_ascii=False))
            return 1
        result = ship_autonomous.process_item(item, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("success") else 1

    summary = ship_autonomous.run_autonomous_queue(max_items=args.max_items, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok", 0) > 0 or summary.get("processed") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
