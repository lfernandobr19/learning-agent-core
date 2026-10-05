import { rmSync } from "node:fs";
import { createFinanceStore, addTransaction, summarizeByMonth, setBudget, checkBudgets, addRecurringTransaction, projectCashFlow, saveFinanceStore, loadFinanceStore } from "./finance.js";

const store = createFinanceStore();
addTransaction(store, { type: "income", amountCents: 500000, category: "salary", date: "2026-06-01" });
addTransaction(store, { type: "expense", amountCents: 120000, category: "housing", date: "2026-06-02" });
addRecurringTransaction(store, { type: "expense", amountCents: 9000, category: "internet", dayOfMonth: 5 });
setBudget(store, { month: "2026-06", category: "housing", limitCents: 150000 });
saveFinanceStore(store, "data/smoke-finance-store.json");
const restored = loadFinanceStore("data/smoke-finance-store.json");
rmSync("data/smoke-finance-store.json", { force: true });
console.log(JSON.stringify({ ok: true, summary: summarizeByMonth(restored, "2026-06"), budgets: checkBudgets(restored, "2026-06"), cashflow: projectCashFlow(restored, "2026-06", 2) }));