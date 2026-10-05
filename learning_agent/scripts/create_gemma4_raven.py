#!/usr/bin/env python3
"""Fase 4: destila corpus Ravenna → Ollama gemma4-raven (Gemma4 + few-shots)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from learning_agent.core import finetune  # noqa: E402

OUT = ROOT / "data" / "diagnostics" / "gemma4-raven-build.json"


def main() -> int:
    dry = "--apply" not in sys.argv
    print("==> Export training data...")
    export = finetune.export_training_data(min_pairs=0)
    print(f"    {export['examples']} exemplos -> {export['path']}")

    print("==> Modelfile gemma4-raven...")
    info = finetune.create_gemma4_raven_modelfile()
    print(f"    base: {info['runtime_base']}")
    print(f"    few-shots: {info['few_shot_count']} domínios {info.get('few_shot_domains')}")
    print(f"    {info['modelfile']}")

    if dry:
        print(f"\nDry-run. Para criar: py {Path(__file__).name} --apply")
        print(f"  {info['create_command']}")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({**info, "dry_run": True}, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0

    print("==> ollama create gemma4-raven (pode levar alguns minutos)...")
    result = finetune.create_gemma4_raven_model(dry_run=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in result if k in ("success", "target_model", "few_shot_count", "error", "exit_code")}, indent=2))
    if not result.get("success"):
        return 1
    print(f"\nOK — modelo {result['target_model']} pronto.")
    print("  Atualize scripts/host-gpu.env: OLLAMA_MODEL=gemma4-raven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
