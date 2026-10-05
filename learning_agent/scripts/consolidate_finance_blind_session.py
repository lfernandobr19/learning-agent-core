#!/usr/bin/env python3
"""Consolida sessão blind exams finance-lead + fixes Ravenna (jun/2026)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from learning_agent.core import agent_benchmarks, knowledge  # noqa: E402

BATCH_PATH = ROOT / "data" / "blind_exams_batch_last.json"
LAST_PATH = ROOT / "data" / "blind_exams_last.json"

BODY = """# Consolidação — Blind exams finance-lead (Ravenna)

**Data:** {date}

---

## Objetivo

Amadurecer finance-lead via benchmarks cegos repetíveis, limiar **80%**, variância medida em batch 5×.

---

## O que foi feito (Cursor + Ravenna)

### 1. Limiar de aprovação
- `pass_threshold`: **70% → 80%** em `blind_01`, `blind_02`, `blind_03`
- Fallback scorer: `agent_benchmarks.py`

### 2. Batch variância (antes dos fixes)
- Comando: `python -m learning_agent.scripts.run_finance_blind_exams --batch 5`
- **15 runs** (3 blinds × 5), modelo `qwen2.5:32b`
- Resultado:
  - blind_01: 100% ×5 (σ=0)
  - blind_02: 100% ×5 (σ=0)
  - blind_03: **80% ×5** (σ=0) — falha sistemática em `risk_section` (5/5)
- **0/15** abaixo do limiar, mas blind_03 **grudava no mínimo**

### 3. Fixes aplicados (todos)
| Fix | Arquivo |
|-----|---------|
| Scorer aceita `volatility`/`volatilidade` + exposição | `agent_benchmarks.py` |
| Prompt blind reforça `risk` em PT com drawdown/sizing/stop/volatilidade | `finance_blind_exam.py` |
| Script batch reutiliza prompt compartilhado | `run_finance_blind_exams.py` |
| Playbook documenta blind exams | `agents/projects/finance-lead/playbook.md` |
| `best_score_pct` no dashboard (blind_score 0% → real) | `agent_benchmarks.py` |
| blind_03 tickers sem `.SA` | `blind_03.yaml` |

### 4. Batch pós-fix
{post_fix_summary}

### 5. Automação A / B / C (implementado)
| Opção | Gatilho |
|-------|---------|
| A | Dom 09:30 `run-finance-blind-batch.ps1` |
| B | Overnight ciclo % 10 — batch 5× |
| C | Overnight ciclo % 4 — fresh 1×/blind |

Registrar: `.\\scripts\\register-scheduled-tasks.ps1`

### 6. Audit Ravenna
`python -m learning_agent.scripts.run_ravenna_finance_automation_audit`

### 7. Métricas Prove (referência)
- F1–F11 externo: **11/11**
- Capability: **L6**, score **92**
- Overnight: **{overnight_status}** via `ensure-finance-stack.ps1`

---

## Lições para Ravenna / finance-lead

1. **Confiabilidade de processo ≠ acertar mercado** — blinds medem compliance JSON, não P&L.
2. **Variância intra-cenário baixa** (temp 0.2) — falhas são **sistemáticas**, não aleatórias.
3. **blind_03 era ponto fraco** — campo `risk` genérico em inglês; corrigir prompt + scorer.
4. **Repetir batch 5×** antes de subir limiar ou declarar L6 operacional em decisões reais.
5. **Journal:** toda sessão blind → nota RAG + `benchmark_results.json`.

---

## Comandos

```powershell
python -m learning_agent.scripts.run_finance_blind_exams --batch 5
python -m learning_agent.scripts.consolidate_finance_blind_session
.\\scripts\\ensure-finance-stack.ps1 -Until 2026-06-20T06:00 -Focus l6-operational
```

Tags: finance-lead, blind-exam, ravenna, consolidation, l6-operational
"""


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _format_post_fix(batch: dict) -> str:
    if not batch.get("blinds"):
        return "_Batch pós-fix ainda não rodado._"
    lines = [
        f"- Média global: **{batch.get('overall', {}).get('mean_composite')}%**",
        f"- σ global: **{batch.get('overall', {}).get('stdev_composite')}**",
        f"- Pass: **{batch.get('overall', {}).get('total_pass')}/{batch.get('overall', {}).get('total_runs')}**",
        "",
    ]
    for b in batch.get("blinds") or []:
        fails = b.get("criteria_failures") or {}
        fail_txt = f" falhas={fails}" if fails else ""
        lines.append(
            f"- **{b.get('blind_id')}**: média {b.get('mean_composite')}% "
            f"(min {b.get('min_composite')}, max {b.get('max_composite')}){fail_txt}"
        )
    return "\n".join(lines)


def main() -> int:
    batch = _load_json(BATCH_PATH)
    bench = agent_benchmarks.benchmark_summary("finance-lead")

    overnight_status = "verificar PID"
    try:
        import subprocess

        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-OvernightRootProcesses).Count",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(ROOT),
        )
        count = ps.stdout.strip()
        overnight_status = f"{'ativo' if count and count != '0' else 'iniciar via ensure-finance-stack'}"
    except Exception:
        pass

    body = BODY.format(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        post_fix_summary=_format_post_fix(batch),
        overnight_status=overnight_status,
    )

    note = knowledge.add_note(
        "[Consolidação] Blind exams finance-lead — batch, fixes, limiar 80%",
        body,
        tags=[
            "finance-lead",
            "blind-exam",
            "ravenna",
            "consolidation",
            "l6-operational",
            "workspace-study",
        ],
        sync_cloud=False,
    )

    meta = {
        "note_id": note.get("note_id") or note.get("id"),
        "blind_score_pct": bench.get("best_score_pct"),
        "batch_recorded_at": batch.get("recorded_at"),
        "consolidated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    out = ROOT / "data" / "consolidate_finance_blind_last.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": True, **meta}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
