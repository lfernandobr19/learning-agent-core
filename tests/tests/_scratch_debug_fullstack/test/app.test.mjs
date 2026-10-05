import assert from "node:assert/strict";
import test from "node:test";
import { hashPassword, verifyPassword, createSession } from "../src/auth.js";
import { createStore, createUser, authenticateUser, createProject, listProjects, updateProject, deleteProject } from "../src/store.js";
import { createApp, routeRequest } from "../src/server.js";

test("auth hashes and verifies passwords without storing raw values", () => {
  const hash = hashPassword("strongpass");
  assert.notEqual(hash, "strongpass");
  assert.equal(verifyPassword("strongpass", hash), true);
});

test("auth rejects short passwords", () => {
  assert.throws(() => hashPassword("short"), /at least 8/);
});

test("users can register and login", () => {
  const store = createStore();
  const user = createUser(store, { email: "user@example.com", password: "strongpass" });
  const login = authenticateUser(store, "user@example.com", "strongpass");
  assert.equal(login.user.id, user.id);
  assert.equal(login.session.userId, user.id);
});

test("invalid login is rejected", () => {
  const store = createStore();
  createUser(store, { email: "user@example.com", password: "strongpass" });
  assert.throws(() => authenticateUser(store, "user@example.com", "wrongpass"), /invalid credentials/);
});

test("project CRUD creates, lists and updates owner projects", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  const project = createProject(store, user.id, { title: "Ravenna" });
  assert.equal(listProjects(store, user.id).length, 1);
  assert.equal(updateProject(store, user.id, project.id, { status: "done" }).status, "done");
});

test("delete removes only owner project", () => {
  const store = createStore();
  const user = createUser(store, { email: "owner@example.com", password: "strongpass" });
  const project = createProject(store, user.id, { title: "Ravenna" });
  assert.equal(deleteProject(store, user.id, project.id).deleted, true);
  assert.equal(listProjects(store, user.id).length, 0);
});

test("routeRequest exposes user and project API", () => {
  const app = createApp();
  const created = JSON.parse(routeRequest(app, { method: "POST", path: "/api/users", body: { email: "api@example.com", password: "strongpass" } }).body);
  const project = routeRequest(app, { method: "POST", path: "/api/projects", userId: created.id, body: { title: "API project" } });
  assert.equal(project.status, 201);
  assert.equal(JSON.parse(project.body).title, "API project");
});

test("routeRequest returns validation errors for bad requests", () => {
  const app = createApp();
  const result = routeRequest(app, { method: "POST", path: "/api/users", body: { email: "bad", password: "strongpass" } });
  assert.equal(result.status, 400);
});

test("createSession requires a user", () => {
  assert.throws(() => createSession(null), /user is required/);
});