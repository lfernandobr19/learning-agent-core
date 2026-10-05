import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export function createFinanceStore(snapshot = {}) {
  const store = {
    transactions: new Map(),
    budgets: new Map(),
    goals: new Map(),
    recurring: new Map(),
    nextId: snapshot.nextId || 1,
  };
  for (const item of snapshot.transactions || []) store.transactions.set(item.id, item);
  for (const item of snapshot.budgets || []) store.budgets.set(item.id, item);
  for (const item of snapshot.goals || []) store.goals.set(item.id, item);
  for (const item of snapshot.recurring || []) store.recurring.set(item.id, item);
  return store;
}

function snapshotStore(store) {
  return {
    transactions: [...store.transactions.values()].map((item) => ({ ...item })),
    budgets: [...store.budgets.values()].map((item) => ({ ...item })),
    goals: [...store.goals.values()].map((item) => ({ ...item })),
    recurring: [...store.recurring.values()].map((item) => ({ ...item })),
    nextId: store.nextId,
  };
}

export function saveFinanceStore(store, filePath = "data/finance-store.json") {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, JSON.stringify(snapshotStore(store), null, 2), "utf-8");
  return { saved: true, filePath };
}

export function loadFinanceStore(filePath = "data/finance-store.json") {
  return createFinanceStore(JSON.parse(readFileSync(filePath, "utf-8")));
}

function assertCents(value, name) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer in cents`);
}

function monthOf(date) {
  return String(date || "").slice(0, 7);
}

function nextId(store, prefix) {
  const id = `${prefix}-${store.nextId}`;
  store.nextId += 1;
  return id;
}

export function addTransaction(store, input) {
  const type = input?.type;
  if (!["income", "expense"].includes(type)) throw new Error("type must be income or expense");
  assertCents(input.amountCents, "amountCents");
  if (!input.category) throw new Error("category is required");
  if (!input.date || !/^\d{4}-\d{2}-\d{2}$/.test(input.date)) throw new Error("date must be YYYY-MM-DD");
  const description = input.description || "";
  const duplicate = [...store.transactions.values()].some((transaction) =>
    transaction.type === type &&
    transaction.amountCents === input.amountCents &&
    transaction.category === input.category &&
    transaction.date === input.date &&
    transaction.description === description
  );
  if (!input.id && duplicate) throw new Error("duplicate transaction detected");
  const transaction = {
    id: input.id || nextId(store, "tx"),
    type,
    amountCents: input.amountCents,
    category: input.category,
    date: input.date,
    description,
  };
  store.transactions.set(transaction.id, transaction);
  return { ...transaction };
}

export function listTransactions(store, filters = {}) {
  return [...store.transactions.values()]
    .filter((transaction) => !filters.month || monthOf(transaction.date) === filters.month)
    .filter((transaction) => !filters.type || transaction.type === filters.type)
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((transaction) => ({ ...transaction }));
}

export function summarizeByMonth(store, month) {
  const transactions = listTransactions(store, { month });
  const summary = { month, incomeCents: 0, expenseCents: 0, balanceCents: 0, byCategory: {} };
  for (const transaction of transactions) {
    if (transaction.type === "income") summary.incomeCents += transaction.amountCents;
    if (transaction.type === "expense") {
      summary.expenseCents += transaction.amountCents;
      summary.byCategory[transaction.category] = (summary.byCategory[transaction.category] || 0) + transaction.amountCents;
    }
  }
  summary.balanceCents = summary.incomeCents - summary.expenseCents;
  return summary;
}

export function setBudget(store, input) {
  if (!input?.month || !/^\d{4}-\d{2}$/.test(input.month)) throw new Error("month must be YYYY-MM");
  if (!input.category) throw new Error("category is required");
  assertCents(input.limitCents, "limitCents");
  const key = `${input.month}:${input.category}`;
  const budget = { id: key, month: input.month, category: input.category, limitCents: input.limitCents };
  store.budgets.set(key, budget);
  return { ...budget };
}

export function checkBudgets(store, month) {
  const summary = summarizeByMonth(store, month);
  return [...store.budgets.values()]
    .filter((budget) => budget.month === month)
    .map((budget) => {
      const spentCents = summary.byCategory[budget.category] || 0;
      return {
        ...budget,
        spentCents,
        remainingCents: budget.limitCents - spentCents,
        overspent: spentCents > budget.limitCents,
      };
    });
}

export function addGoal(store, input) {
  assertCents(input?.targetCents, "targetCents");
  assertCents(input?.savedCents || 0, "savedCents");
  const goal = {
    id: input.id || nextId(store, "goal"),
    name: input.name || "Goal",
    targetCents: input.targetCents,
    savedCents: input.savedCents || 0,
    monthlyContributionCents: input.monthlyContributionCents || 0,
    targetDate: input.targetDate || null,
  };
  assertCents(goal.monthlyContributionCents, "monthlyContributionCents");
  store.goals.set(goal.id, goal);
  return { ...goal };
}

export function projectGoal(store, goalId) {
  const goal = store.goals.get(goalId);
  if (!goal) throw new Error("goal not found");
  const remainingCents = Math.max(0, goal.targetCents - goal.savedCents);
  const monthsToTarget = goal.monthlyContributionCents > 0 ? Math.ceil(remainingCents / goal.monthlyContributionCents) : null;
  const onTrack = goal.targetDate && monthsToTarget !== null
    ? monthsToTarget <= monthsBetween(new Date().toISOString().slice(0, 10), goal.targetDate)
    : null;
  return { ...goal, remainingCents, monthsToTarget, onTrack };
}

export function addRecurringTransaction(store, input) {
  const template = {
    id: input.id || nextId(store, "rec"),
    type: input.type,
    amountCents: input.amountCents,
    category: input.category,
    description: input.description || "",
    dayOfMonth: input.dayOfMonth || 1,
  };
  if (!["income", "expense"].includes(template.type)) throw new Error("type must be income or expense");
  assertCents(template.amountCents, "amountCents");
  store.recurring.set(template.id, template);
  return { ...template };
}

export function materializeRecurring(store, month) {
  if (!/^\d{4}-\d{2}$/.test(month)) throw new Error("month must be YYYY-MM");
  const created = [];
  for (const template of store.recurring.values()) {
    const date = `${month}-${String(template.dayOfMonth).padStart(2, "0")}`;
    const id = `${template.id}:${month}`;
    if (!store.transactions.has(id)) {
      created.push(addTransaction(store, { ...template, id, date }));
    }
  }
  return created;
}

function addMonths(month, offset) {
  const [year, rawMonth] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, rawMonth - 1 + offset, 1));
  return date.toISOString().slice(0, 7);
}

function monthsBetween(startDate, endDate) {
  const [startYear, startMonth] = startDate.slice(0, 7).split("-").map(Number);
  const [endYear, endMonth] = endDate.slice(0, 7).split("-").map(Number);
  return Math.max(0, (endYear - startYear) * 12 + (endMonth - startMonth));
}

export function projectCashFlow(store, startMonth, months = 3) {
  if (!/^\d{4}-\d{2}$/.test(startMonth)) throw new Error("startMonth must be YYYY-MM");
  const projections = [];
  for (let index = 0; index < months; index += 1) {
    const month = addMonths(startMonth, index);
    const summary = summarizeByMonth(store, month);
    for (const template of store.recurring.values()) {
      if (template.type === "income") summary.incomeCents += template.amountCents;
      if (template.type === "expense") summary.expenseCents += template.amountCents;
    }
    summary.balanceCents = summary.incomeCents - summary.expenseCents;
    projections.push(summary);
  }
  return projections;
}

export function exportCsv(store) {
  const rows = ["id,date,type,category,amountCents,description"];
  for (const transaction of listTransactions(store)) {
    rows.push([transaction.id, transaction.date, transaction.type, transaction.category, transaction.amountCents, transaction.description.replaceAll(",", " ")].join(","));
  }
  return `${rows.join("\n")}\n`;
}