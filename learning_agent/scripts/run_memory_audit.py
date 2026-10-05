"""Run Ravenna memory audit in read-only dry-run mode."""

from __future__ import annotations

import argparse
import json
import sys

from learning_agent.core import memory_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria somente leitura da memória Ravenna")
    parser.add_argument("--limit", type=int, default=10, help="Máximo de amostras por seção")
    parser.add_argument("--no-chroma", action="store_true", help="Não contar documentos Chroma")
    parser.add_argument("--curate", action="store_true", help="Gerar plano de curadoria reversível")
    parser.add_argument("--apply", action="store_true", help="Marcar duplicatas como superseded (sem DELETE)")
    parser.add_argument("--max-batches", type=int, default=1, help="Máximo de lotes por tabela na curadoria")
    parser.add_argument("--all-batches", action="store_true", help="Rodar lotes até não restarem grupos duplicados")
    parser.add_argument("--summary-only", action="store_true", help="Omitir detalhes de grupos do relatório")
    parser.add_argument("--restore", action="store_true", help="Restaurar memória superseded para active")
    parser.add_argument("--table", default="", help="Tabela alvo para restore")
    parser.add_argument("--canonical-id", type=int, default=None, help="Canonical id alvo para restore")
    args = parser.parse_args()

    if args.restore:
        report = memory_audit.restore_superseded_memory(
            table=args.table or None,
            canonical_id=args.canonical_id,
            limit=args.limit,
        )
    elif args.curate:
        max_batches = 10_000 if args.all_batches else args.max_batches
        report = memory_audit.run_memory_curation(
            apply=args.apply,
            limit=args.limit,
            max_batches=max_batches,
            include_groups=not args.summary_only,
        )
    else:
        report = memory_audit.run_memory_audit(limit=args.limit, include_chroma=not args.no_chroma)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
