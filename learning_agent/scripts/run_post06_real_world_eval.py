"""Post-06 real-world evaluation for Ravenna Cursor parity.

The overnight suite proves known contracts. This script probes more Cursor-like
work: ambiguous product requests, incremental changes in an existing project,
and legacy bug fixes.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from learning_agent.api import app
from learning_agent.config import PROJECT_ROOT


OUT_DIR = PROJECT_ROOT / "data" / "diagnostics" / "post06-real-world"


def _read(root: Path, rel: str) -> str:
    path = root / rel
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _run_delivery(client: TestClient, message: str, project: str) -> dict[str, Any]:
    response = client.post(
        "/api/software/delivery/run",
        json={
            "message": message,
            "project_root": project,
            "auto_apply": True,
            "run_validation": True,
            "use_model_rounds": False,
            "max_repair_rounds": 1,
        },
        timeout=260,
    )
    return {"statusCode": response.status_code, "body": response.json()}


def _run_autonomy(client: TestClient, message: str, project: str) -> dict[str, Any]:
    response = client.post(
        "/api/agent/autonomy/run",
        json={
            "message": message,
            "context": "Post-06 real-world repo eval",
            "agent": "backend-lead",
            "mode": "agent",
            "project_root": project,
            "auto_apply": True,
            "model_size": "0.5b",
            "persist_history": False,
            "max_repair_attempts": 3,
            "run_checklist": True,
        },
        timeout=260,
    )
    return {"statusCode": response.status_code, "body": response.json()}


def _token_check(root: Path, required: dict[str, list[str]]) -> list[str]:
    failures: list[str] = []
    for rel, tokens in required.items():
        text = _read(root, rel)
        if not text:
            failures.append(f"{rel} missing")
            continue
        failures.extend(f"{rel} missing `{token}`" for token in tokens if token not in text)
    return failures


def _prepare_legacy_project(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "test").mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(
        json.dumps({"type": "module", "scripts": {"test": "node --test test/*.mjs"}}, indent=2),
        encoding="utf-8",
    )
    (root / "src" / "cart.js").write_text(
        """export function totalCart(items) {
  return items.reduce((total, item) => total + item.priceCents, 0);
}
""",
        encoding="utf-8",
    )
    (root / "test" / "cart.test.mjs").write_text(
        """import assert from "node:assert/strict";
import test from "node:test";
import { totalCart } from "../src/cart.js";

test("totalCart multiplies price by quantity", () => {
  assert.equal(totalCart([{ priceCents: 500, quantity: 3 }]), 1500);
});
""",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    runs: list[dict[str, Any]] = []

    open_project = "data/diagnostics/post06-real-world/open-helpdesk-product"
    open_root = PROJECT_ROOT / open_project
    if open_root.exists():
        shutil.rmtree(open_root)
    open_result = _run_delivery(
        client,
        (
            "Tenho uma ideia de produto B2B: um helpdesk interno para times pequenos. "
            "Entregue um MVP completo com login, tickets, prioridades, dashboard HTML acessível, testes e README. "
            "Escolha a arquitetura simples e implemente sem dependências externas."
        ),
        open_project,
    )
    open_failures = _token_check(
        open_root,
        {
            "src/auth.js": ["hashPassword", "createSession"],
            "src/store.js": ["createTicket", "listTickets", "updateTicket"],
            "src/server.js": ["/api/login", "/api/tickets"],
            "public/index.html": ["Ticket", "aria-label"],
            "test/app.test.mjs": ["ticket", "auth"],
        },
    )
    runs.append({
        "id": "open-helpdesk-product",
        "statusCode": open_result["statusCode"],
        "passed": bool(open_result["body"].get("passed")) and not open_failures,
        "failures": open_failures,
    })

    incremental_project = "data/diagnostics/post06-real-world/incremental-saas"
    incremental_root = PROJECT_ROOT / incremental_project
    if incremental_root.exists():
        shutil.rmtree(incremental_root)
    base_result = _run_delivery(
        client,
        "Crie um software completo para operações SaaS: auth, CRUD de clientes/projetos, billing em centavos, ledger auditável, dashboard HTML acessível e API roteável",
        incremental_project,
    )
    enhancement_result = _run_delivery(
        client,
        (
            "No projeto existente, adicione audit log para criação de projetos e invoices, export CSV do ledger, "
            "e preserve auth, CRUD, billing e todos os testes existentes."
        ),
        incremental_project,
    )
    incremental_failures = _token_check(
        incremental_root,
        {
            "src/audit.js": ["recordAuditEvent", "listAuditEvents"],
            "src/billing.js": ["exportLedgerCsv", "summarizeLedger"],
            "test/app.test.mjs": ["audit", "CSV"],
        },
    )
    runs.append({
        "id": "incremental-existing-saas",
        "basePassed": bool(base_result["body"].get("passed")),
        "statusCode": enhancement_result["statusCode"],
        "passed": bool(enhancement_result["body"].get("passed")) and not incremental_failures,
        "failures": incremental_failures,
    })

    legacy_project = "data/diagnostics/post06-real-world/legacy-cart-bugfix"
    legacy_root = PROJECT_ROOT / legacy_project
    _prepare_legacy_project(legacy_root)
    legacy_result = _run_autonomy(
        client,
        (
            "Corrija o bug no projeto existente: totalCart deve multiplicar priceCents por quantity, "
            "validar quantity inteiro positivo, preservar API exportada e manter `npm test` passando. "
            "Arquivos alvo: src/cart.js, test/cart.test.mjs. ```shell\nnpm test\n```"
        ),
        legacy_project,
    )
    legacy_failures = _token_check(
        legacy_root,
        {
            "src/cart.js": ["quantity", "priceCents * item.quantity"],
            "test/cart.test.mjs": ["integer", "positive"],
        },
    )
    runs.append({
        "id": "legacy-cart-bugfix",
        "statusCode": legacy_result["statusCode"],
        "passed": bool((legacy_result["body"].get("autonomy") or {}).get("passed")) and not legacy_failures,
        "failures": legacy_failures,
    })

    passed = sum(1 for item in runs if item.get("passed"))
    report = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs": runs,
        "summary": {
            "runs": len(runs),
            "passed": passed,
            "successRate": round(passed / max(1, len(runs)), 4),
            "ok": passed == len(runs),
        },
    }
    (OUT_DIR / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if not report["summary"]["ok"]:
        print("POST06_GAPS " + json.dumps([run for run in runs if not run.get("passed")], ensure_ascii=False))
    return report


def main() -> int:
    return 0 if run()["summary"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
