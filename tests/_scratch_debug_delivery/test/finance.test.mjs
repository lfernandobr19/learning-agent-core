import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  createFinanceStore,
  addTransaction,
  listTransactions,
  summarizeByMonth,
  setBudget,
  checkBudgets,
  addGoal,
  projectGoal,
  addRecurringTransaction,
  materializeRecurring,
  projectCashFlow,
  saveFinanceStore,
  loadFinanceStore,
  exportCsv,
} from "../src/finance.js";
import { createApp, routeRequest } from "../src/server.js";

test("transaction records income and expense using integer cents", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addTransaction(store, { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02" });
  assert.equal(listTransactions(store).length, 2);
});

test("transaction rejects invalid cents", () => {
  const store = createFinanceStore();
  assert.throws(() => addTransaction(store, { type: "expense", amountCents: 12.5, category: "food", date: "2026-06-02" }), /amountCents/);
});

test("transaction detects duplicates", () => {
  const store = createFinanceStore();
  const input = { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02", description: "Market" };
  addTransaction(store, input);
  assert.throws(() => addTransaction(store, input), /duplicate transaction/);
});

test("monthly summary computes income expense and balance", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addTransaction(store, { type: "expense", amountCents: 100000, category: "rent", date: "2026-06-02" });
  const summary = summarizeByMonth(store, "2026-06");
  assert.equal(summary.balanceCents, 400000);
});

test("summary ignores other months", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-05-01" });
  assert.equal(summarizeByMonth(store, "2026-06").incomeCents, 0);
});

test("budget tracks remaining amount", () => {
  const store = createFinanceStore();
  setBudget(store, { month: "2026-06", category: "food", limitCents: 100000 });
  addTransaction(store, { type: "expense", amountCents: 40000, category: "food", date: "2026-06-10" });
  assert.equal(checkBudgets(store, "2026-06")[0].remainingCents, 60000);
});

test("budget detects overspend", () => {
  const store = createFinanceStore();
  setBudget(store, { month: "2026-06", category: "food", limitCents: 100000 });
  addTransaction(store, { type: "expense", amountCents: 140000, category: "food", date: "2026-06-10" });
  assert.equal(checkBudgets(store, "2026-06")[0].overspent, true);
});

test("goal projection returns months to target", () => {
  const store = createFinanceStore();
  const goal = addGoal(store, { name: "Emergency", targetCents: 1200000, savedCents: 300000, monthlyContributionCents: 100000, targetDate: "2027-12-01" });
  assert.equal(projectGoal(store, goal.id).monthsToTarget, 9);
  assert.equal(projectGoal(store, goal.id).onTrack, true);
});

test("goal projection handles no monthly contribution", () => {
  const store = createFinanceStore();
  const goal = addGoal(store, { name: "Trip", targetCents: 100000, savedCents: 0 });
  assert.equal(projectGoal(store, goal.id).monthsToTarget, null);
});

test("recurring transactions materialize once per month", () => {
  const store = createFinanceStore();
  addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
  assert.equal(materializeRecurring(store, "2026-06").length, 1);
  assert.equal(materializeRecurring(store, "2026-06").length, 0);
});

test("cashflow projection includes recurring transactions", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
  addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
  const projection = projectCashFlow(store, "2026-06", 2);
  assert.equal(projection[0].balanceCents, 491000);
  assert.equal(projection[1].balanceCents, -9000);
});

test("store persists and loads from local JSON", () => {
  const dir = mkdtempSync(join(tmpdir(), "finance-store-"));
  const filePath = join(dir, "store.json");
  try {
    const store = createFinanceStore();
    addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
    saveFinanceStore(store, filePath);
    const restored = loadFinanceStore(filePath);
    assert.equal(listTransactions(restored).length, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("CSV export includes transaction data", () => {
  const store = createFinanceStore();
  addTransaction(store, { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02", description: "Market" });
  assert.match(exportCsv(store), /food,12500/);
});

test("routeRequest creates transactions through API", () => {
  const app = createApp();
  const result = routeRequest(app, { method: "POST", path: "/api/transactions", body: { type: "expense", amountCents: 12500, category: "food", date: "2026-06-02" } });
  assert.equal(result.status, 201);
});

test("routeRequest returns budget checks", () => {
  const app = createApp();
  routeRequest(app, { method: "POST", path: "/api/budgets", body: { month: "2026-06", category: "food", limitCents: 100000 } });
  const result = routeRequest(app, { method: "GET", path: "/api/budgets", query: { month: "2026-06" } });
  assert.equal(JSON.parse(result.body)[0].category, "food");
});

test("routeRequest exposes goal projection", () => {
  const app = createApp();
  const goal = JSON.parse(routeRequest(app, { method: "POST", path: "/api/goals", body: { name: "Emergency", targetCents: 100000, savedCents: 0, monthlyContributionCents: 50000 } }).body);
  const projection = routeRequest(app, { method: "GET", path: `/api/goals/${goal.id}` });
  assert.equal(JSON.parse(projection.body).monthsToTarget, 2);
});

test("routeRequest serves mobile CSS", () => {
  const app = createApp();
  const response = routeRequest(app, { method: "GET", path: "/styles.css" });
  assert.equal(response.headers["content-type"], "text/css");
  assert.match(response.body, /min-height: 44px/);
});