"""Overnight stress suite for Cursor-level Ravenna software delivery.

This suite intentionally goes beyond the fixed 8/8 benchmark. It runs practical
large-delivery prompts, validates the generated projects, and emits a stable
sentinel when a gap needs follow-up.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.config import PROJECT_ROOT


OUT_DIR = PROJECT_ROOT / "data" / "diagnostics" / "cursor-level-stress"


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "finance-family-office-mobile",
        "endpoint": "/api/software/delivery/run",
        "project": "data/diagnostics/cursor-level-stress/finance-family-office-mobile",
        "message": (
            "Crie um sistema de controle financeiro pessoal completo Node.js sem dependências externas, compatível com celular. "
            "Inclua persistência local JSON, orçamento recorrente, metas por prazo, projeção de fluxo de caixa, "
            "detecção de lançamentos duplicados, inadimplência/atrasos e export CSV."
        ),
        "required_tokens": {
            "src/finance.js": [
                "projectCashFlow",
                "saveFinanceStore",
                "duplicate transaction",
                "targetDate",
                "materializeRecurring",
                "exportCsv",
            ],
            "public/index.html": ["viewport", "aria-live", "/api/transactions"],
        },
    },
    {
        "id": "fullstack-auth-crm",
        "endpoint": "/api/software/delivery/run",
        "project": "data/diagnostics/cursor-level-stress/fullstack-auth-crm",
        "message": (
            "Crie um software fullstack CRUD com auth Node.js sem dependências externas. "
            "O sistema deve permitir cadastro, login, sessão, CRUD de projetos por usuário, UI HTML acessível, "
            "API roteável, isolamento básico por usuário e smoke test."
        ),
        "required_tokens": {
            "src/auth.js": ["hashPassword", "verifyPassword", "createSession"],
            "src/store.js": ["createProject", "listProjects", "updateProject", "deleteProject"],
            "src/server.js": ["routeRequest", "/api/login", "/api/projects"],
            "public/index.html": ["<form", "aria-label"],
        },
    },
    {
        "id": "fulfillment-return-backorder-saga",
        "endpoint": "/api/agent/autonomy/run",
        "project": "data/diagnostics/cursor-level-stress/fulfillment-return-backorder-saga",
        "message": (
            "Crie um order fulfillment engine event-sourced Node.js sem dependências externas. "
            "Arquivos obrigatórios: package.json, README.md, src/fulfillment.js, src/cli.js, fixtures/events.jsonl, test/fulfillment.test.mjs. "
            "requiredExports para src/fulfillment.js = [createStore, applyCommand, replayEvents, parseJsonl, snapshotState]. "
            "Use commandId, processedCommandIds, eventos OrderReserved, PaymentCaptured, OrderShipped, OrderCancelled, "
            "ReturnRequested, RefundIssued, BackorderCreated e *Rejected. Suporte múltiplos depósitos/warehouses, "
            "backorder quando estoque faltar, devolução/refund depois de envio, e snapshotState defensivo. "
            "Use totalCents, unitPriceCents, amountCents e refundCents como inteiros. Inclua pelo menos 10 testes. "
            "```shell\nnpm test\n```\n```shell\nnpm run smoke\n```"
        ),
        "required_tokens": {
            "src/fulfillment.js": ["snapshotState", "BackorderCreated", "ReturnRequested", "RefundIssued"],
            "test/fulfillment.test.mjs": ["parseJsonl", "replayEvents", "snapshotState"],
        },
    },
    {
        "id": "multi-domain-ops-suite",
        "endpoint": "/api/software/delivery/run",
        "project": "data/diagnostics/cursor-level-stress/multi-domain-ops-suite",
        "message": (
            "Crie um software completo para operações SaaS: auth, CRUD de clientes/projetos, billing em centavos, "
            "ledger auditável, dashboard HTML acessível e API roteável, sem dependências externas. "
            "Inclua testes de auth, CRUD, billing e smoke."
        ),
        "required_tokens": {
            "src/auth.js": ["hashPassword", "createSession"],
            "src/store.js": ["createProject", "listProjects"],
            "src/billing.js": ["totalCents", "ledger"],
            "test/app.test.mjs": ["auth", "billing", "project"],
        },
        "known_gap": "multi-domain orchestrator",
    },
]


def _read_text(project: str, rel_path: str) -> str:
    path = PROJECT_ROOT / project / rel_path
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _post(client: TestClient, scenario: dict[str, Any]) -> dict[str, Any]:
    endpoint = scenario["endpoint"]
    payload: dict[str, Any] = {
        "message": scenario["message"],
        "project_root": scenario["project"],
    }
    if endpoint == "/api/software/delivery/run":
        payload.update({
            "auto_apply": True,
            "run_validation": True,
            "use_model_rounds": False,
            "max_repair_rounds": 1,
        })
    else:
        payload.update({
            "context": f"Cursor-level stress scenario {scenario['id']}",
            "agent": "backend-lead",
            "mode": "agent",
            "auto_delegate": False,
            "model_size": "0.5b",
            "persist_history": False,
            "auto_apply": True,
            "max_repair_attempts": 3,
            "run_checklist": True,
        })
    response = client.post(endpoint, json=payload, timeout=260)
    return {"statusCode": response.status_code, "body": response.json()}


def run_once(label: str = "once") -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    runs: list[dict[str, Any]] = []

    for scenario in SCENARIOS:
        started = time.time()
        try:
            result = _post(client, scenario)
            body = result.get("body") or {}
            passed = bool(body.get("passed") or (body.get("autonomy") or {}).get("passed"))
            failures: list[str] = []
            for rel_path, tokens in (scenario.get("required_tokens") or {}).items():
                text = _read_text(scenario["project"], rel_path)
                missing = [token for token in tokens if token not in text]
                failures.extend(f"{rel_path} missing token `{token}`" for token in missing)
            if failures:
                passed = False
            runs.append({
                "id": scenario["id"],
                "project": scenario["project"],
                "statusCode": result["statusCode"],
                "passed": passed,
                "failures": failures,
                "knownGap": scenario.get("known_gap"),
                "elapsedSeconds": round(time.time() - started, 2),
            })
        except Exception as exc:
            runs.append({
                "id": scenario["id"],
                "project": scenario["project"],
                "passed": False,
                "failures": [repr(exc)],
                "knownGap": scenario.get("known_gap"),
                "elapsedSeconds": round(time.time() - started, 2),
            })

    passed_count = sum(1 for run in runs if run.get("passed"))
    report = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "label": label,
        "runs": runs,
        "summary": {
            "runs": len(runs),
            "passed": passed_count,
            "successRate": round(passed_count / max(1, len(runs)), 4),
            "ok": passed_count == len(runs),
        },
    }
    out = OUT_DIR / "latest.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"RAVENNA_STRESS_RESULT {json.dumps(report['summary'], ensure_ascii=False)}", flush=True)
    if not report["summary"]["ok"]:
        print(f"AGENT_LOOP_WAKE_OVERNIGHT_STRESS {json.dumps({'report': str(out), 'failures': [r for r in runs if not r.get('passed')]}, ensure_ascii=False)}", flush=True)
    return report


def _parse_until(value: str) -> datetime:
    now = datetime.now()
    hour, minute = [int(part) for part in value.split(":", 1)]
    end_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if end_at <= now:
        end_at += timedelta(days=1)
    return end_at


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--until", default="06:00")
    parser.add_argument("--interval", type=int, default=1800)
    args = parser.parse_args()

    if args.once:
        return 0 if run_once()["summary"]["ok"] else 2

    end_at = _parse_until(args.until)
    cycle = 0
    while datetime.now() < end_at:
        cycle += 1
        run_once(label=f"cycle-{cycle}")
        remaining = (end_at - datetime.now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(max(120, min(args.interval, int(remaining))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
