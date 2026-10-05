#!/usr/bin/env python3
"""Ravenna audita automação blind finance-lead — avalia, ensina, consolida."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent.core import agent_benchmarks, chat, knowledge  # noqa: E402

AUDIT_LOG = ROOT / "data" / "ravenna_finance_automation_audit_last.json"

CONTEXT = """
## Automação implementada (finance-lead blind exams)

### Opção A — Semanal (Task Scheduler)
- Script: scripts/scheduled/run-finance-blind-batch.ps1
- Tarefa: Ravenna-LearningAgent-BlindBatch (domingo 09:30)
- Ação: batch 5× + consolidate + alerta Telegram

### Opção B — Overnight batch
- run_finance_lead_overnight.py — ciclo %% FINANCE_BLIND_BATCH_EVERY_CYCLES (default 10)
- batch 5× com LLM fresco, alerta Telegram

### Opção C — Overnight fresh
- Mesmo overnight — ciclo %% FINANCE_BLIND_FRESH_EVERY_CYCLES (default 4), exceto quando B roda
- 1 resposta LLM por blind (todos os blinds)

### Limiar: 80% | Prompt: finance_blind_exam.BLIND_EXAM_SYSTEM
### Scorer: volatilidade/volatility aceitos em risk_section
"""


def _load_batch_summary() -> str:
    batch = ROOT / "data" / "blind_exams_batch_last.json"
    fresh = ROOT / "data" / "blind_exams_fresh_last.json"
    parts = []
    for label, path in [("batch", batch), ("fresh", fresh)]:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                overall = data.get("overall") or {}
                parts.append(
                    f"{label}: mean={overall.get('mean_composite')}% "
                    f"pass={overall.get('total_pass')}/{overall.get('total_runs')}"
                )
            except json.JSONDecodeError:
                pass
    bench = agent_benchmarks.benchmark_summary("finance-lead")
    parts.append(f"best_score_pct={bench.get('best_score_pct')}")
    return "\n".join(parts) or "sem runs recentes"


def run_audit(*, persist: bool = True) -> dict:
    metrics = _load_batch_summary()
    user_msg = f"""Você é a Ravenna orquestrando o finance-lead.

Revise a automação de blind exams abaixo e responda em português com:

1. **Veredito** (OK / ATENÇÃO / FALHA) — 1 linha
2. **Coerência L6** — alinha com playbook e F5 (decisão sob incerteza)?
3. **Gaps** — o que falta para confiabilidade operacional (máx 3 bullets)
4. **Próximo passo** — 1 ação concreta para o overnight ou domingo

Métricas recentes:
{metrics}

{CONTEXT}
"""

    result = chat.reply(
        user_msg,
        channel="ide",
        user_id="ravenna-finance-automation-audit",
        include_context=True,
        delegate_agent="finance-lead",
        task_mode="chat",
        model_size="32b",
        persist_history=False,
    )

    reply = result.get("reply") or result.get("error") or ""
    audit = {
        "success": result.get("success", False),
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model": result.get("model"),
        "metrics": metrics,
        "reply": reply,
        "error": result.get("error"),
    }

    note_id = None
    if persist and reply:
        note = knowledge.add_note(
            "[Ravenna audit] Automação blind exams finance-lead",
            f"# Audit Ravenna — blind automation\n\n{reply}\n\n---\n\nMétricas:\n{metrics}",
            tags=["finance-lead", "ravenna", "blind-exam", "automation", "audit"],
            sync_cloud=False,
        )
        note_id = note.get("note_id") or note.get("id")
        audit["note_id"] = note_id

    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_LOG.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    audit = run_audit()
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit.get("success") and audit.get("reply") else 1


if __name__ == "__main__":
    raise SystemExit(main())
