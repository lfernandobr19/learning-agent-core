import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "./store.js";

export function createApp(store = createStore()) {
  return { store };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function routeRequest(app, request) {
  const { method, path, body = {}, userId } = request;
  try {
    if (method === "GET" && path === "/") return { status: 200, headers: { "content-type": "text/html" }, body: readFileSync("public/index.html", "utf-8") };
    if (method === "POST" && path === "/api/users") return json(201, createUser(app.store, body));
    if (method === "POST" && path === "/api/login") return json(200, authenticateUser(app.store, body.email, body.password));
    if (method === "GET" && path === "/api/projects") return json(200, listProjects(app.store, userId));
    if (method === "POST" && path === "/api/projects") return json(201, createProject(app.store, userId, body));
    if (method === "PATCH" && path.startsWith("/api/projects/")) return json(200, updateProject(app.store, userId, path.split("/").pop(), body));
    if (method === "DELETE" && path.startsWith("/api/projects/")) return json(200, deleteProject(app.store, userId, path.split("/").pop()));
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
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf-8")) : {};
      const result = routeRequest(app, { method: req.method, path: new URL(req.url, "http://localhost").pathname, body });
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    });
  });
  server.listen(3000, () => console.log("listening on http://localhost:3000"));
}