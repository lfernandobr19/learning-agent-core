"""Small code-pattern reminders for Ravenna Agent prompts."""

from __future__ import annotations

from typing import Any


PATTERNS = {
    "node-test-native": """node:test native pattern:
```js
import assert from "node:assert/strict";
import test from "node:test";

test("does something", () => {
  assert.equal(1 + 1, 2);
});
```
Never use describe/it/expect unless a test framework is installed.""",
    "esm-no-require": """ESM CLI pattern:
```js
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  // run CLI
}
```
Never use require() in a package with type: module.""",
    "node-cli-testable": """Testable Node CLI pattern:
```js
// src/cli.js
import { fileURLToPath } from "node:url";

export function sumNumbers(values) {
  return values.reduce((total, value) => total + Number(value), 0);
}

export function runCli(argv = process.argv.slice(2), write = console.log) {
  const sum = sumNumbers(argv);
  write(JSON.stringify({ sum }));
  return { sum };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) runCli();
```
```js
// test/cli.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { runCli, sumNumbers } from "../src/cli.js";

test("sumNumbers sums values", () => {
  assert.equal(sumNumbers(["1", "2", "3"]), 6);
});

test("runCli writes JSON", () => {
  const output = [];
  runCli(["4", "5"], (line) => output.push(line));
  assert.deepEqual(JSON.parse(output[0]), { sum: 9 });
});
```
In tests, import exported functions directly. Do not use TestContext, t.equal, t.spy, t.stub, firstCall, or Jest-style mocks. Do not import from ./lib/* unless that file is required and written.""",
    "event-sourcing": """Event-sourcing pattern:
- decide(command, state) returns events.
- applyEvent(state, event) mutates state.
- applyCommand runs decide then applyEvent.
- replayEvents applies events from an empty store.
- rejection events end with Rejected and must not corrupt state.""",
    "fulfillment-event-sourcing": """Fulfillment event-sourcing blueprint:
```js
export function createStore() {
  return {
    orders: new Map(),
    inventory: new Map(),
    processedCommandIds: new Set(),
    events: [],
  };
}

export function applyCommand(store, command) {
  if (!command?.commandId) throw new Error("commandId is required");
  if (store.processedCommandIds.has(command.commandId)) return { duplicate: true, events: [] };
  const events = decide(store, command);
  for (const event of events) applyEvent(store, event);
  store.processedCommandIds.add(command.commandId);
  store.events.push(...events);
  return { duplicate: false, events };
}
```
Domain contract:
- Accept explicit commands such as ReserveOrder, CapturePayment, ShipOrder, CancelOrder.
- Also tolerate event-like command aliases OrderReserved, PaymentCaptured, OrderShipped, OrderCancelled when commandId is present.
- Emit events named OrderReserved, PaymentCaptured, OrderShipped, OrderCancelled, plus *Rejected events for invalid transitions.
- OrderReserved must store items with unitPriceCents and compute totalCents as integer cents.
- PaymentCaptured must validate amountCents as an integer and compare it with totalCents.
- replayEvents should support both replayEvents(events) and replayEvents(store, events).
- parseJsonl(text) must throw `Invalid JSONL at line N: ...` for malformed non-empty lines.
Keep command decision, event application, replayEvents, parseJsonl, and CLI separate. Do not self-import `./fulfillment.js` from inside `src/fulfillment.js`. Do not reduce the test suite below minTests during repair.""",
    "idempotency": """Idempotency pattern:
- Store processedCommandIds as a Set.
- If commandId was seen, return duplicate=true and emit no events.
- Add commandId only after applying the command's events.""",
    "integer-cents": """Money pattern:
- Use unitPriceCents, amountCents, totalCents as integers.
- Never use floats for money.
- Validate integer cents with Number.isInteger(value) and value >= 0.""",
    "jsonl-line-errors": """JSONL pattern:
```js
export function parseJsonl(text) {
  return text.split(/\\r?\\n/).map((line, index) => {
    if (!line.trim()) return null;
    try { return JSON.parse(line); }
    catch (error) { throw new Error(`Invalid JSONL at line ${index + 1}: ${error.message}`); }
  }).filter(Boolean);
}
```""",
    "python-pytest": """Python pytest pattern:
```py
# src/habit_score.py
def calculate_habit_score(habits):
    if not isinstance(habits, list):
        raise ValueError("habits must be a list")
    total = 0
    for habit in habits:
        if not isinstance(habit, dict) or "status" not in habit or "points" not in habit:
            raise ValueError("each habit needs status and points")
        if habit["status"] not in {"completed", "skipped", "missed"}:
            raise ValueError("invalid status")
        total += int(habit["points"]) if habit["status"] == "completed" else 0
    return {"score": total}
```
Keep implementation and tests consistent. Run pytest from the project root.""",
    "python-src-imports": """Python src-layout imports:
- Put implementation in src/<module>.py.
- Tests may use `from src.<module> import name`.
- The runner also sets PYTHONPATH to project root and src, so `import <module>` is accepted.
- Do not write tests outside the project root.""",
}


def patterns_for_spec(spec: dict[str, Any], *, max_patterns: int = 4) -> str:
    rules = spec.get("semanticRules") or []
    if "event-sourcing" in rules and "idempotency" in rules and "fulfillment-event-sourcing" not in rules:
        rules = ["fulfillment-event-sourcing", *rules]
    selected: list[str] = []
    for rule in rules:
        pattern = PATTERNS.get(rule)
        if pattern:
            selected.append(pattern)
        if len(selected) >= max_patterns:
            break
    if not selected:
        return ""
    return "PADRÕES OBRIGATÓRIOS RELEVANTES:\n\n" + "\n\n".join(selected)
