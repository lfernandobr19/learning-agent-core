from __future__ import annotations

import json
import shutil

from fastapi.testclient import TestClient

from learning_agent import api
from learning_agent.api import app
from learning_agent.core import agent_autonomy_runner, agent_critic, agent_reliability, agent_spec_builder, software_delivery
from learning_agent.core.workspace import resolve_path


def test_parse_write_blocks_deduplicates_and_normalizes():
    text = """Vou aplicar.

```write tests/_scratch_autonomy/a.js
export const a = 1
```

```write tests\\_scratch_autonomy\\a.js
export const a = 2
```
"""

    blocks = agent_autonomy_runner.parse_write_blocks(text)

    assert len(blocks) == 1
    assert blocks[0].path == "tests/_scratch_autonomy/a.js"
    assert blocks[0].content == "export const a = 2"


def test_apply_write_blocks_saves_files():
    scratch = "tests/_scratch_autonomy/applied.txt"
    try:
        result = agent_autonomy_runner.apply_write_blocks(
            "```write tests/_scratch_autonomy/applied.txt\nok\n```"
        )

        assert result["blockCount"] == 1
        assert result["changedPaths"][0].endswith(scratch)
        assert resolve_path(scratch).read_text(encoding="utf-8") == "ok"
    finally:
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def test_apply_write_blocks_scopes_relative_paths_to_project_root():
    scratch = "tests/_scratch_autonomy_scoped/package.json"
    try:
        result = agent_autonomy_runner.apply_write_blocks(
            "```write package.json\n{\"type\":\"module\"}\n```",
            base_path="tests/_scratch_autonomy_scoped",
        )

        assert result["blockCount"] == 1
        assert result["changedPaths"][0].endswith(scratch)
        assert resolve_path(scratch).is_file()
    finally:
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        if path.parent.exists():
            path.parent.rmdir()


def test_apply_write_blocks_scopes_remoteapp_project_root():
    scratch = "data/remote-workspaces/remote_app-teste/tests/_scratch_remoteapp_scope/flag.txt"
    try:
        result = agent_autonomy_runner.apply_write_blocks(
            "```write tests/_scratch_remoteapp_scope/flag.txt\nremoteapp ok\n```",
            base_path="data/remote-workspaces/remote_app-teste",
        )

        assert result["blockCount"] == 1
        assert result["changedPaths"][0].endswith("tests/_scratch_remoteapp_scope/flag.txt")
        assert resolve_path(scratch).read_text(encoding="utf-8") == "remote_app ok"
    finally:
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        for parent in [path.parent, path.parent.parent]:
            if parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    pass


def test_apply_write_blocks_scopes_canonical_workspace_paths_once():
    scratch = "tests/_scratch_autonomy_scoped_canonical/package.json"
    try:
        result = agent_autonomy_runner.apply_write_blocks(
            "```write learning-agent/tests/_scratch_autonomy_scoped_canonical/package.json\n{\"type\":\"module\"}\n```",
            base_path="tests/_scratch_autonomy_scoped_canonical",
        )

        assert result["blockCount"] == 1
        assert result["changedPaths"][0].endswith(scratch)
        assert resolve_path(scratch).is_file()
        assert not resolve_path("tests/_scratch_autonomy_scoped_canonical/learning-agent").exists()
    finally:
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        if path.parent.exists():
            path.parent.rmdir()


def test_apply_write_blocks_scopes_tests_folder_to_project_root():
    scratch = "tests/_scratch_autonomy_scoped_tests/tests/test_app.py"
    leaked = "tests/test_app.py"
    try:
        result = agent_autonomy_runner.apply_write_blocks(
            "```write tests/test_app.py\nassert True\n```",
            base_path="tests/_scratch_autonomy_scoped_tests",
        )

        assert result["changedPaths"][0].endswith(scratch)
        assert resolve_path(scratch).is_file()
        assert not resolve_path(leaked).exists()
    finally:
        resolve_path(leaked).unlink(missing_ok=True)
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        for parent in [path.parent, path.parent.parent]:
            if parent.exists():
                parent.rmdir()


def test_safe_shell_blocks_blocks_unsafe_commands():
    result = agent_autonomy_runner.run_safe_shell_blocks(
        "```shell\nnpm run dev\n```\n```shell\nnpm test && del important.txt\n```"
    )

    assert result["blockCount"] == 2
    assert result["ok"] is True
    assert len(result["blocked"]) == 2
    assert all(item["skipped"] for item in result["ran"])


def test_shell_parser_ignores_shell_fences_inside_write_blocks():
    text = """```write README.md
```shell
npm test
```
```
```shell
npm run smoke
```"""

    blocks = agent_autonomy_runner.parse_shell_blocks(text)

    assert [block.command for block in blocks] == ["npm run smoke"]


def test_shell_parser_splits_multiple_validation_commands():
    blocks = agent_autonomy_runner.parse_shell_blocks(
        "```shell\npy -m py_compile src/habit_score.py\npy -m pytest tests/test_habit_score.py\n```"
    )

    assert [block.command for block in blocks] == [
        "py -m py_compile src/habit_score.py",
        "py -m pytest tests/test_habit_score.py",
    ]


def test_safe_shell_blocks_runs_allowlisted_node_command():
    result = agent_autonomy_runner.run_safe_shell_blocks("```shell\nnode -e \"console.log('ok')\"\n```")

    assert result["blockCount"] == 1
    assert result["ok"] is True
    assert result["blocked"]


def test_safe_shell_blocks_runs_python_compile_in_project():
    root = resolve_path("tests/_scratch_autonomy_shell")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps({"type": "module"}), encoding="utf-8")
        (root / "sample.py").write_text("x = 1\n", encoding="utf-8")

        result = agent_autonomy_runner.run_safe_shell_blocks(
            "```shell\npy -m py_compile sample.py\n```",
            project_root="tests/_scratch_autonomy_shell",
            timeout_seconds=30,
        )

        assert result["blockCount"] == 1
        assert result["ok"] is True
        assert result["ran"][0]["exit_code"] == 0
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_node_test_checklist_rejects_jest_globals_with_node_test():
    root = resolve_path("tests/_scratch_autonomy_node")
    try:
        (root / "test").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "type": "module",
                    "scripts": {"test": "node --test test/billing.test.mjs", "start": "node src/cli.js"},
                }
            ),
            encoding="utf-8",
        )
        (root / "test" / "billing.test.mjs").write_text(
            'describe("x", () => { it("y", () => expect(1).toBe(1)) })\n',
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Node.js type: module billing project",
            ["tests/_scratch_autonomy_node/package.json"],
            None,
        )

        assert result["ok"] is False
        assert any("Jest" in failure for failure in result["failures"])
        assert any("node:test" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_configurable_checklist_required_files_and_exports():
    root = resolve_path("tests/_scratch_autonomy_config")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps(
                {
                    "type": "module",
                    "scripts": {"test": "node --test", "start": "node src/cli.js"},
                    "ravenna": {
                        "autonomy": {
                            "moneySafe": False,
                            "requiredFiles": ["README.md", "src/billing.js"],
                            "requiredExports": {"src/billing.js": ["calculateInvoice", "parseUsageCsv"]},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (root / "src" / "billing.js").write_text(
            "export function calculateInvoice() { return {} }\n",
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Node.js type: module project",
            ["tests/_scratch_autonomy_config/src/billing.js"],
            None,
        )

        assert result["ok"] is False
        assert any("README.md" in failure for failure in result["failures"])
        assert any("parseUsageCsv" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_inferred_required_files_are_enforced():
    root = resolve_path("tests/_scratch_autonomy_inferred")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps({"type": "module", "scripts": {"test": "node --test"}}), encoding="utf-8")

        result = agent_autonomy_runner.check_project_requirements(
            "Crie README.md, src/fulfillment.js, src/cli.js e test/fulfillment.test.mjs",
            ["tests/_scratch_autonomy_inferred/package.json"],
            None,
        )

        assert result["ok"] is False
        assert any("README.md" in failure for failure in result["failures"])
        assert any("test/fulfillment.test.mjs" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_semantic_fulfillment_checklist_rejects_weak_domain_model():
    root = resolve_path("tests/_scratch_autonomy_fulfillment")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "test").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "node --test", "start": "node src/cli.js"}}),
            encoding="utf-8",
        )
        (root / "src" / "fulfillment.js").write_text(
            "export function createStore(){return {}}\nexport function applyCommand(){return {}}\nexport function replayEvents(){}\nexport function parseJsonl(){}\n",
            encoding="utf-8",
        )
        (root / "src" / "cli.js").write_text("const fs = require('fs')\n", encoding="utf-8")
        (root / "test" / "fulfillment.test.mjs").write_text(
            "import test from 'node:test'; import assert from 'node:assert/strict'; test('one',()=>assert.equal(1,1))\n",
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Crie order fulfillment event-sourced com pelo menos 7 testes, commandId, totalCents, parseJsonl reporta linha",
            ["tests/_scratch_autonomy_fulfillment/src/fulfillment.js"],
            None,
        )

        assert result["ok"] is False
        assert any("require" in failure for failure in result["failures"])
        assert any("commandId" in failure for failure in result["failures"])
        assert any("7" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_spec_builder_extracts_contract_for_fulfillment_prompt():
    spec = agent_spec_builder.build_spec(
        """
        Crie em data/bench/app package.json, src/fulfillment.js, src/cli.js e test/fulfillment.test.mjs.
        requiredExports para src/fulfillment.js = [createStore, applyCommand, replayEvents, parseJsonl]
        Use node:test, ESM, commandId, totalCents e pelo menos 7 testes.
        ```shell
        npm test
        ```
        ```shell
        npm run smoke
        ```
        """,
        project_root="data/bench/app",
    )

    assert spec["projectRoot"] == "data/bench/app"
    assert "src/fulfillment.js" in spec["requiredFiles"]
    assert spec["requiredExports"]["src/fulfillment.js"] == ["createStore", "applyCommand", "replayEvents", "parseJsonl"]
    assert spec["validationCommands"] == ["npm test", "npm run smoke"]
    assert "node-test-native" in spec["semanticRules"]
    assert "idempotency" in spec["semanticRules"]
    assert spec["minTests"] == 7
    assert spec["complexity"] == "complex"


def test_fulfillment_spec_does_not_load_generic_sum_cli_pattern():
    spec = agent_spec_builder.build_spec(
        """
        Crie package.json, src/fulfillment.js, src/cli.js e test/fulfillment.test.mjs para Node CLI.
        Fulfillment event-sourced com commandId, totalCents, unitPriceCents, amountCents e pelo menos 7 testes.
        """,
        project_root="data/bench/app",
    )
    prompt, _ = api._build_autonomy_prompt(
        """
        Crie package.json, src/fulfillment.js, src/cli.js e test/fulfillment.test.mjs para Node CLI.
        Fulfillment event-sourced com commandId, totalCents, unitPriceCents, amountCents e pelo menos 7 testes.
        """,
        "data/bench/app",
    )

    assert "node-cli-testable" not in spec["semanticRules"]
    assert "FASE 1/3 - DOMÍNIO PURO OBRIGATÓRIO" in prompt
    assert "SOMENTE `src/fulfillment.js`" in prompt
    assert "sumNumbers" not in prompt
    assert "OrderReserved" in prompt
    assert "ReserveOrder/CapturePayment/ShipOrder/CancelOrder" in prompt
    assert "replayEvents(store, events)" in prompt


def test_spec_builder_preserves_tsx_extensions():
    spec = agent_spec_builder.build_spec(
        "Crie package.json, README.md, src/StatusCard.tsx e src/StatusCard.test.tsx para React TypeScript",
        project_root="data/react-card",
    )

    assert "src/StatusCard.tsx" in spec["requiredFiles"]
    assert "src/StatusCard.test.tsx" in spec["requiredFiles"]
    assert "src/StatusCard.ts" not in spec["requiredFiles"]


def test_fulfillment_base_uses_deterministic_contract_reply():
    message = """
    Crie um order fulfillment engine event-sourced Node.js sem dependências em `data/bench/fulfillment`.
    Arquivos obrigatórios: package.json, README.md, src/fulfillment.js, src/cli.js, fixtures/events.jsonl, test/fulfillment.test.mjs.
    src/fulfillment.js deve exportar createStore, applyCommand, replayEvents, parseJsonl.
    Use commandId, processedCommandIds, eventos OrderReserved, PaymentCaptured, OrderShipped, OrderCancelled e *Rejected.
    Use totalCents, unitPriceCents, amountCents como inteiros. parseJsonl deve reportar linha inválida.
    Use node:test e node:assert/strict, ESM sem require. Inclua pelo menos 7 testes.
    ```shell
    npm test
    ```
    ```shell
    npm run smoke
    ```
    """
    spec = agent_spec_builder.build_spec(message, project_root="data/bench/fulfillment")

    reply = api._build_deterministic_autonomy_reply(message, spec)

    assert reply is not None
    assert "```write src/fulfillment.js" in reply
    assert "```write src/cli.js" in reply
    assert "```write fixtures/events.jsonl" in reply
    assert "snapshotState" in reply
    assert reply.count("test(") >= 7


def test_complex_autonomy_runs_domain_tests_and_cli_phases(monkeypatch):
    root = resolve_path("tests/_scratch_autonomy_phases")
    message = """
    Crie em tests/_scratch_autonomy_phases package.json, src/fulfillment.js, src/cli.js e test/fulfillment.test.mjs.
    Use Node ESM, node:test, fulfillment event-sourced, commandId, totalCents, unitPriceCents, amountCents e pelo menos 7 testes.
    ```shell
    npm test
    ```
    ```shell
    npm run smoke
    ```
    """
    phase_prompts: list[str] = []

    def fake_reply(prompt, **kwargs):
        phase_prompts.append(prompt)
        if "FASE 2/3" in prompt:
            reply = (
                "```write package.json\n"
                "{\"type\":\"module\",\"scripts\":{\"test\":\"node --test\",\"smoke\":\"node src/cli.js\"}}\n"
                "```\n"
                "```write test/fulfillment.test.mjs\n"
                "import test from 'node:test';\n"
                "test('one', () => {});\n"
                "```\n"
            )
        else:
            reply = (
                "```write src/cli.js\nexport function runCli() {}\n```\n"
                "```write test/fulfillment.test.mjs\n// should be ignored in cli phase\n```"
            )
        return {"success": True, "reply": reply}

    def fake_evaluate(request, spec, applied):
        return (
            {"ok": True, "validated": True, "failures": [], "projectRoot": str(root)},
            {"ok": True, "failures": [], "warnings": [], "projectRoot": str(root)},
            {"repairPrompt": "", "recommendedModelSize": "32b"},
            True,
        )

    try:
        monkeypatch.setattr(api.chat, "reply", fake_reply)
        monkeypatch.setattr(api, "_evaluate_autonomy_attempt", fake_evaluate)
        request = api.ChatMessageRequest(
            message=message,
            mode="agent",
            auto_apply=True,
            project_root=str(root),
            max_repair_attempts=0,
        )

        result = api._run_agent_autonomy_cycle(
            request,
            {"success": True, "reply": "```write src/fulfillment.js\nexport function createStore() {}\n```"},
            delegate=None,
        )

        assert result["passed"] is True
        assert [attempt.get("phase") for attempt in result["attempts"][:4]] == ["domain", "tests", "cli", "final-validation"]
        assert any("FASE 2/3 - TESTES OBRIGATÓRIOS" in prompt for prompt in phase_prompts)
        assert any("FASE 3/3 - CLI/SMOKE OBRIGATÓRIO" in prompt for prompt in phase_prompts)
        assert (root / "src" / "fulfillment.js").is_file()
        assert (root / "test" / "fulfillment.test.mjs").read_text(encoding="utf-8") != "// should be ignored in cli phase"
        assert (root / "src" / "cli.js").is_file()
        assert "test/fulfillment.test.mjs" in result["attempts"][2]["applied"]["ignoredPaths"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_phase_filter_accepts_project_prefixed_paths():
    reply = (
        "```write data/diagnostics/app/src/fulfillment.js\nexport const ok = true;\n```\n"
        "```write data/diagnostics/app/test/fulfillment.test.mjs\n// wrong phase\n```"
    )

    filtered = api._filter_write_blocks_for_paths(reply, ["src/fulfillment.js"])
    ignored = api._ignored_write_paths(reply, ["src/fulfillment.js"])

    assert "src/fulfillment.js" in filtered
    assert "wrong phase" not in filtered
    assert ignored == ["data/diagnostics/app/test/fulfillment.test.mjs"]


def test_contract_reconciliation_generates_canonical_fulfillment_tests():
    root = resolve_path("tests/_scratch_contract_reconciliation")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "src" / "fulfillment.js").write_text(
            "export function createStore() { return { orders: new Map(), inventory: new Map(), processedCommandIds: new Set(), events: [] }; }\n"
            "export function applyCommand() { return { duplicate: false, events: [] }; }\n"
            "export function replayEvents() { return createStore(); }\n"
            "export function parseJsonl() { return []; }\n",
            encoding="utf-8",
        )
        request = api.ChatMessageRequest(
            message="Crie fulfillment event-sourced com 7 testes",
            project_root=str(root),
            mode="agent",
            auto_apply=True,
        )
        spec = {
            "complexity": "complex",
            "requiredFiles": ["package.json", "src/fulfillment.js", "test/fulfillment.test.mjs"],
            "requiredExports": {"src/fulfillment.js": ["createStore", "applyCommand", "replayEvents", "parseJsonl"]},
            "semanticRules": ["event-sourcing", "integer-cents", "idempotency", "node-test-native"],
            "minTests": 7,
        }

        reply = api._build_contract_reconciliation_reply(
            request,
            spec,
            {"projectRoot": str(root), "failures": ["npm test exited 1"], "commands": [{"output": "ReferenceError: test is not defined"}]},
            {"failures": ["test/fulfillment.test.mjs não importa `node:test`."]},
            {"failures": []},
        )

        assert reply is not None
        assert 'import test from "node:test";' in reply
        assert 'import assert from "node:assert/strict";' in reply
        assert reply.count("test(") >= 8
        assert "ReserveOrder" in reply
        assert "replayEvents(existingStore, events)" in reply
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_contract_reconciliation_can_replace_broken_fulfillment_domain():
    root = resolve_path("tests/_scratch_contract_reconciliation_domain")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "src" / "fulfillment.js").write_text(
            "import { JSONParseError } from './errors';\n"
            "export function createStore() { return {}; }\n"
            "export function applyCommand() { return {}; }\n"
            "export function replayEvents() { return {}; }\n"
            "export function parseJsonl() { return []; }\n",
            encoding="utf-8",
        )
        request = api.ChatMessageRequest(message="Crie fulfillment event-sourced", project_root=str(root), mode="agent", auto_apply=True)
        spec = {
            "complexity": "complex",
            "requiredFiles": ["package.json", "src/fulfillment.js", "test/fulfillment.test.mjs"],
            "requiredExports": {"src/fulfillment.js": ["createStore", "applyCommand", "replayEvents", "parseJsonl"]},
            "semanticRules": ["event-sourcing", "integer-cents", "idempotency", "node-test-native"],
            "minTests": 7,
        }

        reply = api._build_contract_reconciliation_reply(
            request,
            spec,
            {"projectRoot": str(root), "failures": ["npm test exited 1"], "commands": [{"output": "src/fulfillment.js Error [ERR_MODULE_NOT_FOUND]: Cannot find module './errors'"}]},
            {"failures": ["Fulfillment deve emitir eventos de rejeição sem corromper estado."]},
            {"failures": []},
        )

        assert reply is not None
        assert "```write src/fulfillment.js" in reply
        assert "import { JSONParseError }" not in reply
        assert "function rejected(command, reason)" in reply
        assert "export function replayEvents(storeOrEvents, maybeEvents)" in reply
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_contract_reconciliation_generates_multi_warehouse_variant():
    root = resolve_path("tests/_scratch_contract_reconciliation_multi_warehouse")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "src" / "fulfillment.js").write_text(
            "export function createStore() { return { orders: new Map(), inventory: new Map(), processedCommandIds: new Set(), events: [] }; }\n"
            "export function applyCommand() { return { duplicate: false, events: [] }; }\n"
            "export function replayEvents() { return createStore(); }\n"
            "export function parseJsonl() { return []; }\n",
            encoding="utf-8",
        )
        request = api.ChatMessageRequest(
            message="Crie fulfillment event-sourced com warehouses, backorder, refund e snapshotState",
            project_root=str(root),
            mode="agent",
            auto_apply=True,
        )
        spec = {
            "complexity": "complex",
            "requiredFiles": ["package.json", "README.md", "src/fulfillment.js", "src/cli.js", "fixtures/events.jsonl", "test/fulfillment.test.mjs"],
            "requiredExports": {"src/fulfillment.js": ["createStore", "applyCommand", "replayEvents", "parseJsonl", "snapshotState"]},
            "semanticRules": ["event-sourcing", "integer-cents", "idempotency", "node-test-native"],
            "minTests": 10,
        }

        reply = api._build_contract_reconciliation_reply(
            request,
            spec,
            {"projectRoot": str(root), "failures": ["src/fulfillment.js não exporta snapshotState"], "commands": [{"output": "ReferenceError: Deno is not defined"}]},
            {"failures": ["Suíte insuficiente: 8 testes encontrados, mínimo 10.", "README.md não encontrado."]},
            {"failures": []},
        )

        assert reply is not None
        assert "```write README.md" in reply
        assert "```write src/cli.js" in reply
        assert "```write fixtures/events.jsonl" in reply
        assert "export function snapshotState(store)" in reply
        assert "BackorderCreated" in reply
        assert "ReturnRequested" in reply
        assert "RefundIssued" in reply
        assert reply.count("test(") >= 11
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_software_delivery_spec_routes_work_orders_to_specialists():
    spec = software_delivery.build_software_spec(
        "Crie um software fullstack CRUD com auth Node.js sem dependências externas",
        project_root="tests/_scratch_delivery_spec",
    )

    assert spec["domain"] == "fullstack-crud-auth"
    assert "src/auth.js" in spec["requiredFiles"]
    assert spec["requiredExports"]["src/server.js"] == ["createApp", "routeRequest"]
    agents = {order["agent"] for order in spec["workOrders"]}
    assert "backend-lead" in agents
    assert "frontend-lead" in agents
    assert "qa-guardian" in agents
    assert "reliability-lead" in agents


def test_software_delivery_endpoint_runs_fullstack_gates():
    root = resolve_path("tests/_scratch_delivery_fullstack")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "Crie um software fullstack CRUD com auth Node.js sem dependências externas",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        body = response.json()

        assert response.status_code == 200
        assert body["passed"] is True
        assert all(gate["ok"] for gate in body["gates"])
        assert body["deliveryReport"]["status"] == "passed"
        assert len(body["attempts"]) >= 4
        assert {attempt["agent"] for attempt in body["attempts"]} >= {"backend-lead", "frontend-lead", "qa-guardian", "reliability-lead"}
        assert (root / "src" / "auth.js").is_file()
        assert (root / "test" / "app.test.mjs").is_file()
        assert body["deliveryReport"]["changedPaths"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_software_delivery_spec_routes_saas_ops_suite_to_composite_agents():
    spec = software_delivery.build_software_spec(
        "Crie um software completo para operações SaaS: auth, CRUD de clientes/projetos, billing em centavos e ledger auditável",
        project_root="tests/_scratch_delivery_saas_spec",
    )

    assert spec["domain"] == "saas-ops-suite"
    assert "src/billing.js" in spec["requiredFiles"]
    assert spec["requiredExports"]["src/billing.js"] == ["createBillingLedger", "addInvoice", "recordPayment", "summarizeLedger"]
    assert spec["minTests"] >= 10
    agents = {order["agent"] for order in spec["workOrders"]}
    assert {"backend-lead", "finance-lead", "frontend-lead", "qa-guardian", "reliability-lead"} <= agents


def test_software_delivery_endpoint_runs_saas_ops_suite_gates():
    root = resolve_path("tests/_scratch_delivery_saas_ops")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "Crie um software completo para operações SaaS: auth, CRUD de clientes/projetos, billing em centavos, ledger auditável, dashboard HTML acessível e API roteável",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        body = response.json()

        assert response.status_code == 200
        assert body["passed"] is True
        assert all(gate["ok"] for gate in body["gates"])
        assert body["deliveryReport"]["status"] == "passed"
        assert len(body["attempts"]) >= 5
        assert {attempt["agent"] for attempt in body["attempts"]} >= {"backend-lead", "finance-lead", "frontend-lead", "qa-guardian", "reliability-lead"}
        assert (root / "src" / "billing.js").is_file()
        assert "summarizeLedger" in (root / "src" / "billing.js").read_text(encoding="utf-8")
        assert "billing" in (root / "test" / "app.test.mjs").read_text(encoding="utf-8").lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_software_delivery_endpoint_runs_open_helpdesk_product_gates():
    root = resolve_path("tests/_scratch_delivery_helpdesk")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "Tenho uma ideia de produto B2B: um helpdesk interno. Entregue um MVP completo com login, tickets, prioridades, dashboard HTML acessível, testes e README.",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        body = response.json()

        assert response.status_code == 200
        assert body["passed"] is True
        assert body["spec"]["domain"] == "support-helpdesk"
        assert all(gate["ok"] for gate in body["gates"])
        assert "createTicket" in (root / "src" / "store.js").read_text(encoding="utf-8")
        assert 'path === "/api/tickets"' in (root / "src" / "server.js").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_software_delivery_endpoint_runs_incremental_audit_csv_enhancement():
    root = resolve_path("tests/_scratch_delivery_audit_csv")
    try:
        client = TestClient(app)
        base_response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "Crie um software completo para operações SaaS: auth, CRUD de clientes/projetos, billing em centavos, ledger auditável, dashboard HTML acessível e API roteável",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        assert base_response.json()["passed"] is True

        response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "No projeto existente, adicione audit log para criação de projetos e invoices, export CSV do ledger, e preserve auth, CRUD, billing e todos os testes existentes.",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        body = response.json()

        assert response.status_code == 200
        assert body["passed"] is True
        assert body["spec"]["domain"] == "saas-ops-enhancement"
        assert "recordAuditEvent" in (root / "src" / "audit.js").read_text(encoding="utf-8")
        assert "exportLedgerCsv" in (root / "src" / "billing.js").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cart_bugfix_uses_deterministic_contract_reply():
    reply = api._build_deterministic_autonomy_reply(
        "Corrija totalCart para multiplicar priceCents por quantity e validar quantity inteiro positivo",
        {"requiredFiles": ["src/cart.js", "test/cart.test.mjs"]},
    )

    assert reply is not None
    assert "priceCents * item.quantity" in reply
    assert "non-integer quantity" in reply
    assert "non-positive quantity" in reply


def test_software_delivery_spec_routes_personal_finance_to_finance_lead():
    spec = software_delivery.build_software_spec(
        "Crie um sistema de controle financeiro pessoal compatível com celular",
        project_root="tests/_scratch_delivery_finance_spec",
    )

    assert spec["domain"] == "personal-finance-mobile"
    assert "src/finance.js" in spec["requiredFiles"]
    assert "public/styles.css" in spec["requiredFiles"]
    assert "summarizeByMonth" in spec["requiredExports"]["src/finance.js"]
    assert spec["minTests"] >= 12
    agents = {order["agent"] for order in spec["workOrders"]}
    assert "finance-lead" in agents
    assert "frontend-lead" in agents
    assert "qa-guardian" in agents


def test_software_delivery_endpoint_runs_personal_finance_mobile_gates():
    root = resolve_path("tests/_scratch_delivery_finance_mobile")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/software/delivery/run",
            json={
                "message": "Crie um sistema de controle financeiro pessoal completo compatível com celular",
                "project_root": str(root),
                "auto_apply": True,
                "run_validation": True,
                "use_model_rounds": False,
            },
        )
        body = response.json()

        assert response.status_code == 200
        assert body["passed"] is True
        assert all(gate["ok"] for gate in body["gates"])
        gate_names = {gate["name"] for gate in body["gates"]}
        assert {"mobile_visual_gate", "finance_domain_gate", "cross_review_execution_gate", "security_gate"} <= gate_names
        assert body["deliveryReport"]["status"] == "passed"
        assert len(body["attempts"]) >= 5
        assert {attempt["agent"] for attempt in body["attempts"]} >= {"finance-lead", "backend-lead", "frontend-lead", "qa-guardian", "reliability-lead"}
        assert all(attempt["reviewPassed"] for attempt in body["attempts"])
        assert len(body["crossReviews"]) == len(body["attempts"])
        assert (root / "src" / "finance.js").is_file()
        assert (root / "public" / "styles.css").is_file()
        assert "saveFinanceStore" in (root / "src" / "finance.js").read_text(encoding="utf-8")
        assert "projectCashFlow" in (root / "src" / "finance.js").read_text(encoding="utf-8")
        assert "finance-lead" in {order["agent"] for order in body["spec"]["workOrders"]}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_software_delivery_can_accept_real_specialist_model_rounds():
    root = resolve_path("tests/_scratch_delivery_model_rounds")
    try:
        def fake_model_runner(*, order, prompt, spec, canonical_reply):
            assert order["agent"]
            assert "Arquivos alvo" in prompt
            return {"success": True, "reply": canonical_reply, "model": "fake-raven"}

        body = software_delivery.run_software_delivery(
            "Crie um sistema de controle financeiro pessoal completo compatível com celular",
            project_root=str(root),
            auto_apply=True,
            run_validation=True,
            use_model_rounds=True,
            model_size="32b",
            model_runner=fake_model_runner,
        )

        assert body["passed"] is True
        assert all(attempt["source"] == "model" for attempt in body["attempts"])
        assert all(attempt["modelRound"]["attempted"] for attempt in body["attempts"])
        assert all(attempt["modelRound"]["model"] == "fake-raven" for attempt in body["attempts"])
        assert all(review["ok"] for review in body["crossReviews"])
        assert any(gate["name"] == "cross_review_execution_gate" and gate["ok"] for gate in body["gates"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_complex_autonomy_forces_32b_model():
    spec = {"complexity": "complex"}

    assert api._autonomy_model_size("0.5b", spec) == "32b"
    assert api._autonomy_model_size("auto", spec) == "32b"


def test_spec_builder_infers_testable_node_cli_exports():
    spec = agent_spec_builder.build_spec(
        "Crie package.json, src/cli.js e test/cli.test.mjs para Node CLI somar números com node:test",
        project_root="data/node-cli",
    )

    assert "node-cli-testable" in spec["semanticRules"]
    assert spec["requiredExports"]["src/cli.js"] == ["sumNumbers", "runCli"]


def test_critic_prefers_surgical_test_repair():
    spec = {"requiredFiles": ["src/fulfillment.js", "test/fulfillment.test.mjs"], "validationCommands": ["npm test"]}
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment com testes",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/fulfillment.js"], "shell": {}},
        validation={"failures": ["npm test ran 0 tests"]},
        checklist={"failures": ["Nenhum arquivo de teste encontrado em `test/`."]},
    )

    assert "validation" in critique["categories"]
    assert critique["nextAction"]["targetFiles"] == ["test/fulfillment.test.mjs"]
    assert "correção cirúrgica" in critique["repairPrompt"]


def test_critic_recommends_32b_for_semantic_complex_failures():
    spec = {
        "complexity": "complex",
        "requiredFiles": ["src/fulfillment.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["event-sourcing", "idempotency"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment event-sourcing",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/fulfillment.js"], "shell": {}},
        validation={"failures": ["OrderReserved missing and commandId idempotency broken"]},
        checklist={"failures": ["Fulfillment deve rastrear idempotência por `commandId`."]},
    )

    assert critique["recommendedModelSize"] == "32b"


def test_critic_adds_strict_node_test_repair_rules():
    spec = {
        "complexity": "complex",
        "requiredFiles": ["src/fulfillment.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["node-test-native", "event-sourcing"],
        "minTests": 7,
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment com node:test",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["test/fulfillment.test.mjs"], "shell": {}},
        validation={"failures": ["ReferenceError: test is not defined"]},
        checklist={"failures": ["test/fulfillment.test.mjs não importa `node:test`.", "Suíte insuficiente: 3 teste(s) encontrados; esperado >= 7."]},
    )

    assert "reescreva o arquivo de teste completo" in critique["repairPrompt"]
    assert "Mantenha pelo menos 7 chamadas top-level" in critique["repairPrompt"]
    assert "adicionar/importar `test`" in critique["repairPrompt"]


def test_critic_keeps_node_test_import_errors_targeted_to_tests():
    spec = {
        "requiredFiles": ["src/fulfillment.js", "src/cli.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["node-test-native", "event-sourcing"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment com node:test",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["test/fulfillment.test.mjs"], "shell": {}},
        validation={"failures": ["SyntaxError: The requested module 'node:test' does not provide an export named 'strictEqual'"]},
        checklist={"failures": ["test/fulfillment.test.mjs não usa assert nativo."]},
    )

    assert critique["nextAction"]["targetFiles"] == ["test/fulfillment.test.mjs"]


def test_critic_targets_tests_when_export_name_is_not_imported_in_test_file():
    spec = {
        "requiredFiles": ["src/fulfillment.js", "src/cli.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["node-test-native", "event-sourcing"],
        "minTests": 7,
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment com node:test",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["test/fulfillment.test.mjs"], "shell": {}},
        validation={"failures": ["test\\fulfillment.test.mjs ReferenceError: createStore is not defined"]},
        checklist={"failures": ["Suíte insuficiente: 2 teste(s) encontrados; esperado >= 7."]},
    )

    assert critique["nextAction"]["targetFiles"] == ["test/fulfillment.test.mjs"]


def test_critic_targets_domain_for_fulfillment_runtime_contract_errors():
    spec = {
        "requiredFiles": ["src/fulfillment.js", "src/cli.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["node-test-native", "event-sourcing"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment event-sourcing",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["test/fulfillment.test.mjs"], "shell": {}},
        validation={"failures": ["src/fulfillment.js:57 TypeError: store is not iterable at replayEvents"]},
        checklist={"failures": []},
    )

    assert critique["nextAction"]["targetFiles"] == ["src/fulfillment.js"]


def test_critic_targets_domain_for_missing_module_imported_by_fulfillment():
    spec = {
        "requiredFiles": ["src/fulfillment.js", "src/cli.js", "test/fulfillment.test.mjs"],
        "semanticRules": ["node-test-native", "event-sourcing"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment event-sourcing",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/fulfillment.js"], "shell": {}},
        validation={"failures": ["src/fulfillment.js Error [ERR_MODULE_NOT_FOUND]: Cannot find module './errors'"]},
        checklist={"failures": []},
    )

    assert critique["nextAction"]["targetFiles"] == ["src/fulfillment.js"]


def test_critic_preserves_fulfillment_exports_during_source_repair():
    spec = {
        "complexity": "complex",
        "requiredFiles": ["src/fulfillment.js", "test/fulfillment.test.mjs"],
        "requiredExports": {"src/fulfillment.js": ["createStore", "applyCommand", "replayEvents", "parseJsonl"]},
        "semanticRules": ["event-sourcing", "idempotency"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie fulfillment event-sourcing",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/fulfillment.js"], "shell": {}},
        validation={"failures": ["Unknown command type: undefined"]},
        checklist={"failures": ["Fulfillment deve implementar replay de eventos.", "`src/fulfillment.js` não exporta `parseJsonl`."]},
    )

    assert "preserve todos estes exports: createStore, applyCommand, replayEvents, parseJsonl" in critique["repairPrompt"]
    assert "Não remova `replayEvents`, `parseJsonl`, `createStore` ou `applyCommand`" in critique["repairPrompt"]


def test_critic_keeps_simple_node_repair_on_fast_model():
    spec = {
        "complexity": "medium",
        "requiredFiles": ["package.json", "src/cli.js", "test/cli.test.mjs"],
        "semanticRules": ["node-test-native", "esm-no-require", "node-cli-testable"],
    }
    critique = agent_critic.critique_attempt(
        original_request="Crie Node CLI simples",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["test/cli.test.mjs"], "shell": {}},
        validation={"failures": ["npm test exited 1"], "commands": [{"command": "npm test", "exit_code": 1, "output": "TypeError: t.spy is not a function"}]},
        checklist={"failures": []},
    )

    assert critique["recommendedModelSize"] == "0.5b"


def test_critic_prefers_pytest_target_for_python_failures():
    spec = {"requiredFiles": ["README.md", "src/habit_score.py", "tests/test_habit_score.py"], "validationCommands": ["py -m pytest"]}
    critique = agent_critic.critique_attempt(
        original_request="Crie Python CLI com pytest",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/habit_score.py"], "shell": {}},
        validation={"failures": ["py -m pytest exited 2"]},
        checklist={"failures": []},
    )

    assert critique["nextAction"]["targetFiles"] == ["tests/test_habit_score.py"]
    assert "pytest" in critique["nextAction"]["summary"]


def test_critic_targets_python_source_for_behavior_failures():
    spec = {"requiredFiles": ["README.md", "src/habit_score.py", "tests/test_habit_score.py"], "validationCommands": ["py -m pytest"]}
    critique = agent_critic.critique_attempt(
        original_request="Crie Python CLI com pytest",
        spec=spec,
        applied={"blockCount": 1, "changedPaths": ["src/habit_score.py"], "shell": {}},
        validation={
            "failures": ["py -m pytest exited 1"],
            "commands": [{"command": "py -m pytest", "exit_code": 1, "output": "E KeyError: 'points'\nE Failed: DID NOT RAISE"}],
        },
        checklist={"failures": []},
    )

    assert critique["nextAction"]["targetFiles"] == ["src/habit_score.py"]
    assert "código Python" in critique["nextAction"]["summary"]


def test_reliability_summary_enforces_success_rates_and_false_successes():
    summary = agent_reliability.summarize_runs(
        [
            {"complexity": "simple", "passed": True, "hasFailures": False},
            {"complexity": "simple", "passed": False, "hasFailures": True},
            {"complexity": "complex", "passed": True, "hasFailures": True},
        ]
    )

    assert summary["falseSuccesses"] == 1
    assert summary["zeroFalseSuccessGate"] is False
    assert summary["groups"]["simple"]["successRate"] == 0.5
    assert summary["reliable"] is False


def test_checklist_uses_spec_min_tests_and_semantic_rules():
    root = resolve_path("tests/_scratch_autonomy_spec")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "test").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "node --test"}}),
            encoding="utf-8",
        )
        (root / "src" / "fulfillment.js").write_text("export function createStore(){return {}}\n", encoding="utf-8")
        (root / "test" / "fulfillment.test.mjs").write_text(
            "import test from 'node:test'; import assert from 'node:assert/strict'; test('one',()=>assert.equal(1,1))\n",
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Crie app",
            ["tests/_scratch_autonomy_spec/src/fulfillment.js"],
            None,
            spec={
                "requiredFiles": ["src/fulfillment.js", "test/fulfillment.test.mjs"],
                "semanticRules": ["event-sourcing"],
                "minTests": 7,
            },
        )

        assert result["ok"] is False
        assert any("Suíte insuficiente" in failure for failure in result["failures"])
        assert any("OrderReserved" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_checklist_enforces_spec_required_exports():
    root = resolve_path("tests/_scratch_autonomy_exports")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps({"type": "module", "scripts": {"test": "node --test"}}), encoding="utf-8")
        (root / "src" / "cli.js").write_text("export function runCli() {}\n", encoding="utf-8")

        result = agent_autonomy_runner.check_project_requirements(
            "Crie Node CLI",
            ["tests/_scratch_autonomy_exports/src/cli.js"],
            "tests/_scratch_autonomy_exports",
            spec={"requiredExports": {"src/cli.js": ["sumNumbers", "runCli"]}, "requiredFiles": ["src/cli.js"]},
        )

        assert result["ok"] is False
        assert any("sumNumbers" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_checklist_rejects_external_dependency_scripts_when_disallowed():
    root = resolve_path("tests/_scratch_autonomy_no_deps")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "npm run lint && node --test", "lint": "eslint ."}}),
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Crie Node.js sem dependências externas",
            ["tests/_scratch_autonomy_no_deps/package.json"],
            "tests/_scratch_autonomy_no_deps",
            spec={"requiredFiles": ["package.json"], "validationCommands": ["npm test"]},
        )

        assert result["ok"] is False
        assert any("dependência externa" in failure for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_python_project_without_package_json_uses_project_root_validation():
    root = resolve_path("tests/_scratch_autonomy_python_validation")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "tests").mkdir(parents=True, exist_ok=True)
        (root / "src" / "habit_score.py").write_text("def calculate_habit_score(items):\n    return sum(items)\n", encoding="utf-8")
        (root / "tests" / "test_habit_score.py").write_text(
            "from src.habit_score import calculate_habit_score\n\n"
            "def test_score():\n"
            "    assert calculate_habit_score([1, 2]) == 3\n",
            encoding="utf-8",
        )

        result = api._run_validation_plan(
            ["tests/_scratch_autonomy_python_validation/src/habit_score.py"],
            "tests/_scratch_autonomy_python_validation",
            spec={"validationCommands": ["py -m pytest"], "requiredFiles": ["src/habit_score.py", "tests/test_habit_score.py"]},
        )

        assert result["ok"] is True
        assert result["commands"][0]["cwd"].endswith("tests\\_scratch_autonomy_python_validation") or result["commands"][0]["cwd"].endswith("tests/_scratch_autonomy_python_validation")
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_money_safe_checklist_requires_cents_total_and_ledger():
    root = resolve_path("tests/_scratch_autonomy_money")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "node --test", "start": "node src/cli.js"}}),
            encoding="utf-8",
        )
        (root / "src" / "billing.js").write_text(
            "export function calculateInvoice() { return { total: 10.25 } }\n",
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Crie um billing de assinatura com invoice",
            ["tests/_scratch_autonomy_money/src/billing.js"],
            None,
        )

        assert result["ok"] is False
        assert any("ledger" in failure.lower() for failure in result["failures"])
        assert any("centavos" in failure.lower() for failure in result["failures"])
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()


def test_integer_cents_rule_does_not_require_billing_ledger_for_fulfillment():
    root = resolve_path("tests/_scratch_autonomy_fulfillment_cents")
    try:
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "node --test"}}),
            encoding="utf-8",
        )
        (root / "src" / "fulfillment.js").write_text(
            "export function createStore() { return {}; }\n"
            "export const totalCents = 100;\n"
            "export const unitPriceCents = 50;\n",
            encoding="utf-8",
        )

        result = agent_autonomy_runner.check_project_requirements(
            "Crie fulfillment event-sourced com centavos",
            ["tests/_scratch_autonomy_fulfillment_cents/src/fulfillment.js"],
            "tests/_scratch_autonomy_fulfillment_cents",
            spec={"semanticRules": ["integer-cents"], "requiredFiles": ["src/fulfillment.js"]},
        )

        assert not any("ledger" in failure.lower() for failure in result["failures"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_autonomy_endpoint_applies_blocks_and_returns_validation(monkeypatch):
    scratch = "tests/_scratch_autonomy_endpoint/out.txt"

    def fake_reply(*args, **kwargs):
        return {
            "success": True,
            "reply": "```write tests/_scratch_autonomy_endpoint/out.txt\nendpoint ok\n```",
            "agent": "Ravenna",
            "model": "fake",
            "conversation_id": "conv-test",
        }

    def fake_validation(changed_paths, project_root=None, spec=None):
        return {
            "ok": True,
            "validated": True,
            "projectRoot": project_root or "tests/_scratch_autonomy_endpoint",
            "commands": [{"command": "fake test", "exit_code": 0, "output": "ok"}],
            "failures": [],
            "skippedReason": None,
        }

    monkeypatch.setattr(api.chat, "reply", fake_reply)
    monkeypatch.setattr(api, "_run_validation_plan", fake_validation)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/agent/autonomy/run",
                json={
                    "message": "crie um arquivo simples",
                    "mode": "agent",
                    "persist_history": False,
                    "run_checklist": False,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["autonomy"]["passed"] is True
        assert body["autonomy"]["attempts"][0]["applied"]["blockCount"] == 1
        assert resolve_path(scratch).read_text(encoding="utf-8") == "endpoint ok"
    finally:
        path = resolve_path(scratch)
        path.unlink(missing_ok=True)
        if path.parent.exists():
            path.parent.rmdir()


def test_validation_plan_fails_when_node_test_runs_zero_tests():
    root = resolve_path("tests/_scratch_autonomy_zero_tests")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(
            json.dumps({"type": "module", "scripts": {"test": "node --test"}}),
            encoding="utf-8",
        )

        result = api._run_validation_plan(
            ["tests/_scratch_autonomy_zero_tests/package.json"],
            None,
        )

        assert result["ok"] is False
        assert result["commands"][0]["zero_tests"] is True
        assert "0 tests" in result["failures"][0]
    finally:
        for path in sorted(root.glob("**/*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()
