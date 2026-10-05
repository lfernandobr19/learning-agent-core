import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
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
} from "./finance.js";

export function createApp(store = createFinanceStore()) {
  return { store };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, query = {} } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "GET" && path === "/styles.css") return { status: 200, headers: { "content-type": "text/css" }, body: readFileSync("public/styles.css", "utf-8") };
    if (method === "POST" && path === "/api/transactions") return json(201, addTransaction(app.store, body));
    if (method === "GET" && path === "/api/transactions") return json(200, listTransactions(app.store, query));
    if (method === "GET" && path === "/api/summary") return json(200, summarizeByMonth(app.store, query.month));
    if (method === "POST" && path === "/api/budgets") return json(201, setBudget(app.store, body));
    if (method === "GET" && path === "/api/budgets") return json(200, checkBudgets(app.store, query.month));
    if (method === "POST" && path === "/api/goals") return json(201, addGoal(app.store, body));
    if (method === "GET" && path.startsWith("/api/goals/")) return json(200, projectGoal(app.store, path.split("/").pop()));
    if (method === "POST" && path === "/api/recurring") return json(201, addRecurringTransaction(app.store, body));
    if (method === "POST" && path === "/api/recurring/materialize") return json(201, materializeRecurring(app.store, body.month));
    if (method === "GET" && path === "/api/cashflow") return json(200, projectCashFlow(app.store, query.startMonth, Number(query.months || 3)));
    if (method === "POST" && path === "/api/persistence/save") return json(200, saveFinanceStore(app.store, body.filePath));
    if (method === "POST" && path === "/api/persistence/load") {
      app.store = loadFinanceStore(body.filePath);
      return json(200, { loaded: true });
    }
    if (method === "GET" && path === "/api/export.csv") return { status: 200, headers: { "content-type": "text/csv" }, body: exportCsv(app.store) };
    return json(404, { error: "not found" });
  } catch (error) {
    return json(400, { error: error.message });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const app = createApp();
  const server = createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      const url = new URL(req.url, "http://localhost");
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const query = Object.fromEntries(url.searchParams.entries());
      const result = routeRequest(app, { method: req.method, path: url.pathname, query, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("finance app listening on http://localhost:3000"));
}