"""Curadoria do corpus de destilação — qualidade > quantidade."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from learning_agent import db
from learning_agent.config import PROJECT_ROOT

REPORT_PATH = PROJECT_ROOT / "data" / "distillation_curation.json"


def curate(*, min_similarity: float = 0.15, min_student_len: int = 80, dry_run: bool = False) -> dict:
    db.init_db()
    removed: list[int] = []
    kept = 0

    with db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, topic, similarity_score, length(student_output) AS slen,
                   length(teacher_output) AS tlen
            FROM distillation_pairs
            ORDER BY id
            """
        ).fetchall()

        for row in rows:
            bad = False
            reason = ""
            if (row["slen"] or 0) < min_student_len:
                bad = True
                reason = "student curto"
            elif (row["similarity_score"] or 0) < min_similarity and (row["tlen"] or 0) > 200:
                bad = True
                reason = "similarity baixa"
            if bad:
                removed.append({"id": row["id"], "topic": row["topic"][:60], "reason": reason})
                if not dry_run:
                    conn.execute("DELETE FROM distillation_pairs WHERE id = ?", (row["id"],))
            else:
                kept += 1

    report = {
        "dry_run": dry_run,
        "min_similarity": min_similarity,
        "min_student_len": min_student_len,
        "kept": kept,
        "removed_count": len(removed),
        "removed": removed[:50],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-similarity", type=float, default=0.15)
    parser.add_argument("--min-student-len", type=int, default=80)
    args = parser.parse_args()

    report = curate(
        min_similarity=args.min_similarity,
        min_student_len=args.min_student_len,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
