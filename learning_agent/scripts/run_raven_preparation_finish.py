"""Completa fases restantes após destilação parcial."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOG = Path("data/raven_preparation_finish.log")


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def wait_model(name: str, timeout_s: int = 7200) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=30)
        if name in (r.stdout or ""):
            return True
        time.sleep(20)
    return False


def main() -> int:
    os.environ.setdefault("STUDENT_MODEL", "phi3:mini")
    from learning_agent import db
    from learning_agent.config import RAVEN_BASE_MODEL
    from learning_agent.core import agent_model_parity, finetune, raven_readiness, software_excellence

    log("=== FINISH: fases restantes ===")
    db.init_db()

    with db.get_connection() as c:
        pairs = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]
    log(f"Pares atuais: {pairs}")

    if pairs < 80:
        log("Groq batch até 80 pares")
        while True:
            with db.get_connection() as c:
                pairs = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]
            if pairs >= 80:
                break
            before = pairs
            batch = software_excellence.run_distillation_batch(
                target_pairs=80,
                max_topics=5,
                broadcast_observer=False,
                refresh_brain=False,
            )
            with db.get_connection() as c:
                pairs = c.execute("SELECT COUNT(*) FROM distillation_pairs").fetchone()[0]
            added = pairs - before
            errs = len(batch.get("errors", []))
            log(f"Groq batch: +{added} pares (total {pairs}/80) erros={errs}")
            if added == 0:
                break

    if not wait_model(RAVEN_BASE_MODEL, timeout_s=60):
        log(f"Pull {RAVEN_BASE_MODEL}")
        subprocess.run(["ollama", "pull", RAVEN_BASE_MODEL], timeout=7200)
        if not wait_model(RAVEN_BASE_MODEL, timeout_s=300):
            log(f"FALHA: {RAVEN_BASE_MODEL} indisponível")
            return 1

    log("Brain pipeline (14B)")
    software_excellence.run_brain_pipeline(dry_run=False, broadcast_observer=False)

    log("Export treino + brain novamente")
    finetune.export_training_data(min_pairs=0)
    software_excellence.run_brain_pipeline(dry_run=False, broadcast_observer=False)

    log("L6 todos agentes")
    from learning_agent.core.agent_capability import CORE_AGENTS

    for slug in CORE_AGENTS:
        try:
            r = agent_model_parity.run_model_parity_assessment(slug, broadcast_observer=False)
            log(f"L6 {slug}: {r.get('composite_score')}")
        except Exception as exc:
            log(f"L6 ERRO {slug}: {exc!r}")

    readiness = raven_readiness.assess_readiness()
    summary = {
        "readiness_pct": readiness["summary"]["readiness_pct"],
        "complete": readiness["complete"],
        "missing": readiness.get("missing", []),
        "pairs": readiness["corpus"]["total_pairs"],
        "cursor_pairs": readiness["corpus"]["cursor_pairs"],
        "training": readiness["corpus"]["training_examples"],
    }
    Path("data/raven_preparation_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"RESULTADO: {json.dumps(summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
