"""Reconstrói o índice RAG (ChromaDB) a partir das notas no SQLite.

Útil quando o índice persistido corrompe (ex.: processo morto no meio de uma
escrita). A fonte de verdade são as tabelas SQLite; o Chroma é só o índice
vetorial e pode ser regenerado com segurança.
"""

from __future__ import annotations

import sys

from learning_agent import db, rag


def reindex_all(batch_log_every: int = 50) -> dict[str, int]:
    db.init_db()
    indexed = 0
    errors = 0

    with db.get_connection() as conn:
        notes = conn.execute(
            "SELECT id, title, content, tags FROM learning_notes ORDER BY id"
        ).fetchall()
        pairs = conn.execute(
            "SELECT id, topic, teacher_output, student_output FROM distillation_pairs ORDER BY id"
        ).fetchall()

    for note in notes:
        try:
            tags = note["tags"] or ""
            rag.index_document(
                f"note:{note['id']}",
                f"{note['title']}\n\n{note['content']}",
                {"type": "note", "title": note["title"], "tags": tags},
            )
            indexed += 1
            if indexed % batch_log_every == 0:
                print(f"  notas indexadas: {indexed}/{len(notes)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ERRO nota #{note['id']}: {exc!r}", flush=True)

    for pair in pairs:
        try:
            rag.index_document(
                f"distill:student:{pair['id']}",
                pair["student_output"] or "",
                {"type": "distillation_student", "topic": pair["topic"], "pair_id": str(pair["id"])},
            )
            indexed += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  ERRO pair #{pair['id']}: {exc!r}", flush=True)

    return {"indexed": indexed, "errors": errors, "notes": len(notes), "pairs": len(pairs)}


def main() -> int:
    if rag.chroma_disabled():
        print(
            "AVISO: RAG_DISABLE_CHROMA está ativo — nenhum documento será indexado. "
            "Desative a variável e rode de novo para rebuild real.",
            flush=True,
        )
    print("Reindexando RAG a partir do SQLite...", flush=True)
    result = reindex_all()
    print(
        f"OK: {result['indexed']} documentos indexados "
        f"({result['notes']} notas + {result['pairs']} pares), {result['errors']} erros.",
        flush=True,
    )
    try:
        count = rag.get_collection().count()
        print(f"Coleção Chroma agora tem {count} documentos.", flush=True)
        hits = rag.search_knowledge("arquitetura de software", limit=3)
        print(f"Teste de busca: {len(hits)} resultados.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Aviso na verificação: {exc!r}", flush=True)
        return 1
    return 0 if result["errors"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
