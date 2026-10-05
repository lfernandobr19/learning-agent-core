#!/usr/bin/env python3
"""Pós-validação — gemma4 corrige lacunas para Ravenna Home completo."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))

from ravenna_home_runtime import (  # noqa: E402
    autonomy_payload,
    load_host_env,
    max_repair_attempts,
    read_timeout,
    safe_mode,
)

load_host_env()

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
CONV = os.environ.get("RAVENNA_HOME_CONV", "conv-df320529dac4")

FIX_BRIEF = """\
**CORREÇÃO PÓS-VALIDAÇÃO — Ravenna Home ferramenta COMPLETA**

Validação Cursor **REPROVOU** (score 28/100). Corrija TUDO abaixo com ```write```/```patch```/```shell```:

1. `learning_agent/core/chat.py` — channel `mobile` + greeting + system prompt Ravenna Home (PT-BR)
2. `agents/curricula/ravenna-home.yaml` — YAML válido com agent, milestones L2–L5
3. `agents/projects/ravenna-home/manifest.yaml` — completo (archetype, learning, mcp_tools, on_failure, files)
4. `ravenna-home/tools/home_devices.py` — corrigir sintaxe; funções async seguras list/toggle/scene
5. `ravenna-home/backend/tests/test_health.py` — pytest real com TestClient FastAPI (health, HA mock, pc_status mock)
6. `ravenna-home/frontend/` — PWA completo: vite, Layout, auth stub, components (Chat, Lights, Scenes, GpuStatus), manifest.json, service worker
7. `ravenna-home/README.md` — PT-BR, setup, arquitetura dual-motor
8. Rodar ```shell cd ravenna-home/backend && pytest -q``` e corrigir até passar

Use get_project_lessons antes. Investigue → Diagnóstico → Solução. Não peça confirmação.
"""


def main() -> int:
    if safe_mode():
        print("AVISO: remediation pesado desabilitado em RAVENNA_SAFE_MODE=1", file=sys.stderr)
        print("Use run_ravenna_home_single_file_fixes.py (1 arquivo por run).", file=sys.stderr)
        return 2
    payload = autonomy_payload(
        FIX_BRIEF,
        conversation_id=CONV,
        project_root="",
        run_checklist=True,
    )
    payload["max_repair_attempts"] = max_repair_attempts(supervisor=True)
    print(f"Correcao gemma4 -> {API} conv={CONV}")
    with httpx.Client(timeout=httpx.Timeout(60.0, read=read_timeout())) as c:
        r = c.post(f"{API}/api/agent/autonomy/run", json=payload)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"detail": r.text[:2000]}
    log = ROOT / "data" / "diagnostics" / "ravenna-home-remediation.json"
    log.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "status": r.status_code, "data": data}, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = bool((data.get("autonomy") or {}).get("passed"))
    print(f"HTTP {r.status_code} autonomy.passed={passed}")
    print(f"Salvo: {log}")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
