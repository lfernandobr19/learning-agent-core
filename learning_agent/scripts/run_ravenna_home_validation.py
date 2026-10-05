#!/usr/bin/env python3
"""Validação conjunta Ravenna Home — gemma4 audita, Cursor audita a auditoria."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "learning_agent" / "scripts"))

from ravenna_home_runtime import load_host_env, model_size, read_timeout  # noqa: E402

load_host_env()

API = os.environ.get("RAVENNA_API_BASE", "http://ravenna-vm:8000").rstrip("/")
CONV = os.environ.get("RAVENNA_HOME_CONV", "conv-df320529dac4")
OUT = ROOT / "data" / "diagnostics" / "ravenna-home-validation.json"
LOG = ROOT / "data" / "diagnostics" / "ravenna-home-validation.jsonl"

VALIDATION_BRIEF = """\
**VALIDAÇÃO OFICIAL — Ravenna Home (ferramenta completa)**

Você é **gemma4-raven** / Ravenna. Audite o projeto `ravenna-home/` e dependências SEM implementar ainda — só diagnóstico estruturado.

Investigue com tools: `read_file`, `list_files`, `grep_workspace`, `get_project_lessons`, `search_knowledge`.

Entregue relatório em markdown com estas seções:

## 1. Checklist MVP (OK / FALHA / PARCIAL)
- README + .env.example
- Backend FastAPI (health, chat proxy channel mobile, HA, PC status)
- PWA React/TS (chat Ravenna, luzes, cenários, GPU)
- `learning_agent/core/chat.py` — channel `mobile` + persona Ravenna Home
- `agents/projects/ravenna-home/manifest.yaml` — agente autônomo completo
- `agents/curricula/ravenna-home.yaml` — marcos L2–L5
- `ravenna-home/tools/home_devices.py` — MCP-ready
- `backend/tests/` — pytest executável

## 2. Testes que você rodaria
Liste comandos ```shell``` e resultado esperado.

## 3. Lacunas para ferramenta COMPLETA
Liste o que falta para produção (PWA manifest, service worker, cenários HA, segurança token, etc.)

## 4. Veredito
`APROVADO` | `APROVADO COM RESSALVAS` | `REPROVADO` — com justificativa.

## 5. Plano de correção (ordem de prioridade)
Máx 8 itens acionáveis.

Não use blocos write/patch nesta rodada — apenas investigação e relatório.
"""

REQUIRED_CHECKS: list[dict[str, Any]] = [
    {"id": "readme", "path": "ravenna-home/README.md"},
    {"id": "env", "path": "ravenna-home/.env.example"},
    {"id": "backend_main", "path": "ravenna-home/backend/main.py"},
    {"id": "backend_ha", "path": "ravenna-home/backend/homeassistant.py"},
    {"id": "backend_pc", "path": "ravenna-home/backend/pc_status.py"},
    {"id": "frontend_app", "path": "ravenna-home/frontend/src/App.tsx"},
    {"id": "frontend_pkg", "path": "ravenna-home/frontend/package.json"},
    {"id": "tests", "path": "ravenna-home/backend/tests/test_health.py"},
    {"id": "tools", "path": "ravenna-home/tools/home_devices.py"},
    {"id": "manifest", "path": "agents/projects/ravenna-home/manifest.yaml"},
    {"id": "curriculum", "path": "agents/curricula/ravenna-home.yaml"},
]


def _log(event: str, **data: Any) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **data}
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_cursor_audit() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in REQUIRED_CHECKS:
        p = ROOT / item["path"]
        files.append({"id": item["id"], "path": item["path"], "exists": p.is_file(), "bytes": p.stat().st_size if p.is_file() else 0})

    chat_py = (ROOT / "learning_agent/core/chat.py").read_text(encoding="utf-8", errors="replace")
    mobile_channel = '"mobile"' in chat_py or "channel == \"mobile\"" in chat_py or "channel == 'mobile'" in chat_py

    manifest = ""
    mp = ROOT / "agents/projects/ravenna-home/manifest.yaml"
    if mp.is_file():
        manifest = mp.read_text(encoding="utf-8")
    manifest_complete = all(k in manifest for k in ("archetype:", "mcp_tools:", "on_failure:", "learning:"))

    curriculum_ok = False
    cp = ROOT / "agents/curricula/ravenna-home.yaml"
    if cp.is_file():
        text = cp.read_text(encoding="utf-8")
        curriculum_ok = "milestones:" in text and "agent:" in text

    tools_syntax_ok = True
    tools_err = ""
    tp = ROOT / "ravenna-home/tools/home_devices.py"
    if tp.is_file():
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(tp)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        tools_syntax_ok = r.returncode == 0
        tools_err = (r.stderr or r.stdout or "")[:400]

    pytest_result: dict[str, Any] = {"ran": False}
    tests_dir = ROOT / "ravenna-home/backend"
    if (tests_dir / "tests").is_dir():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short"],
            capture_output=True,
            text=True,
            cwd=str(tests_dir),
            timeout=120,
        )
        pytest_result = {
            "ran": True,
            "exit_code": r.returncode,
            "stdout": (r.stdout or "")[-2000:],
            "stderr": (r.stderr or "")[-1000:],
        }

    frontend_missing: list[str] = []
    app_tsx = ROOT / "ravenna-home/frontend/src/App.tsx"
    if app_tsx.is_file():
        body = app_tsx.read_text(encoding="utf-8")
        for imp in ("./auth", "./components", "./Layout"):
            if imp in body:
                rel = imp.replace("./", "src/") + (".tsx" if "Layout" in imp or "auth" in imp else "")
                candidates = [
                    ROOT / f"ravenna-home/frontend/{rel}",
                    ROOT / f"ravenna-home/frontend/{rel}x",
                    ROOT / f"ravenna-home/frontend/src/{Path(rel).name}.tsx",
                ]
                if not any(c.is_file() for c in candidates):
                    frontend_missing.append(imp)

    gaps: list[str] = []
    if not mobile_channel:
        gaps.append("channel mobile ausente em learning_agent/core/chat.py")
    if not manifest_complete:
        gaps.append("manifest do agente incompleto (falta archetype, learning estruturado, etc.)")
    if not curriculum_ok:
        gaps.append("curriculum ravenna-home.yaml inválido ou incompleto")
    if not tools_syntax_ok:
        gaps.append(f"home_devices.py com erro de sintaxe: {tools_err[:120]}")
    if pytest_result.get("ran") and pytest_result.get("exit_code") != 0:
        gaps.append("pytest do backend falhou")
    if frontend_missing:
        gaps.append(f"frontend importa módulos inexistentes: {frontend_missing}")
    missing_files = [f["path"] for f in files if not f["exists"]]
    if missing_files:
        gaps.append(f"arquivos ausentes: {missing_files}")

    score = max(0, 100 - 12 * len(gaps))
    verdict = "APROVADO" if score >= 85 and not gaps else "APROVADO COM RESSALVAS" if score >= 55 else "REPROVADO"

    return {
        "auditor": "cursor",
        "verdict": verdict,
        "score": score,
        "files": files,
        "mobile_channel_in_chat_py": mobile_channel,
        "manifest_complete": manifest_complete,
        "curriculum_ok": curriculum_ok,
        "tools_syntax_ok": tools_syntax_ok,
        "pytest": pytest_result,
        "frontend_missing_imports": frontend_missing,
        "gaps": gaps,
    }


def request_ravenna_validation() -> dict[str, Any]:
    payload = {
        "message": VALIDATION_BRIEF,
        "mode": "agent",
        "channel": "ide",
        "conversation_id": CONV,
        "persist_history": True,
        "auto_apply": False,
        "max_repair_attempts": 0,
        "project_root": "ravenna-home",
        "run_checklist": False,
        "model_size": model_size(),
    }
    _log("ravenna_validation_start", conversation_id=CONV)
    t0 = datetime.now(timezone.utc)
    with httpx.Client(timeout=httpx.Timeout(60.0, read=read_timeout())) as client:
        r = client.post(f"{API}/api/chat", json=payload)
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    try:
        data = r.json()
    except Exception:
        data = {"detail": r.text[:4000]}
    report = data.get("message") or data.get("reply") or str(data.get("detail", ""))
    _log("ravenna_validation_end", status=r.status_code, elapsed_s=round(elapsed, 1), chars=len(report))
    return {
        "auditor": "gemma4-raven",
        "status_code": r.status_code,
        "elapsed_s": round(elapsed, 1),
        "report": report,
        "raw": {k: data.get(k) for k in ("agent", "model", "conversation_id", "reasoning")},
    }


def cross_validate(ravenna: dict[str, Any], cursor: dict[str, Any]) -> dict[str, Any]:
    report = (ravenna.get("report") or "").lower()
    ravenna_verdict = "DESCONHECIDO"
    for v in ("reprovado", "aprovado com ressalvas", "aprovado"):
        if v in report:
            ravenna_verdict = v.upper().replace(" COM ", " COM ")
            break

    cursor_gaps = set(cursor.get("gaps") or [])
    aligned: list[str] = []
    missed_by_ravenna: list[str] = []
    for gap in cursor_gaps:
        key = gap.split(":")[0][:30].lower()
        if any(tok in report for tok in key.split() if len(tok) > 4):
            aligned.append(gap)
        else:
            missed_by_ravenna.append(gap)

    overclaimed: list[str] = []
    if "aprovado" in report and "reprovado" not in report.split("veredito")[-1][:80]:
        if cursor.get("verdict") == "REPROVADO":
            overclaimed.append("Ravenna tende a aprovar mas auditoria Cursor reprova")

    agreement = len(aligned) / max(1, len(cursor_gaps))
    return {
        "ravenna_verdict_inferred": ravenna_verdict,
        "cursor_verdict": cursor.get("verdict"),
        "agreement_ratio": round(agreement, 2),
        "aligned_gaps": aligned,
        "missed_by_ravenna": missed_by_ravenna,
        "overclaimed": overclaimed,
        "cursor_gaps": list(cursor_gaps),
    }


def main() -> int:
    print("=== Fase 1: Ravenna/gemma4 valida ===")
    ravenna = request_ravenna_validation()
    print(f"HTTP {ravenna.get('status_code')} em {ravenna.get('elapsed_s')}s")

    print("=== Fase 2: Cursor valida a validação ===")
    cursor = run_cursor_audit()
    cross = cross_validate(ravenna, cursor)

    out = {
        "at": datetime.now(timezone.utc).isoformat(),
        "conversation_id": CONV,
        "ravenna": ravenna,
        "cursor_audit": cursor,
        "cross_validation": cross,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    _log("validation_complete", cursor_verdict=cursor.get("verdict"), cross=cross)

    print(f"\nCursor: {cursor['verdict']} (score {cursor['score']})")
    print(f"Ravenna (inferido): {cross['ravenna_verdict_inferred']}")
    print(f"Acordo em lacunas: {cross['agreement_ratio']*100:.0f}%")
    if cursor["gaps"]:
        print("\nLacunas Cursor:")
        for g in cursor["gaps"]:
            print(f"  - {g}")
    print(f"\nRelatório salvo: {OUT}")
    return 0 if ravenna.get("status_code") == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
