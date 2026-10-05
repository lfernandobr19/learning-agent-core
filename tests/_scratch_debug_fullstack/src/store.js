import { randomUUID } from "node:crypto";
import { createSession, hashPassword, verifyPassword } from "./auth.js";

export function createStore() {
  return { users: new Map(), projects: new Map(), sessions: new Map() };
}

function publicUser(user) {
  const { passwordHash, ...safe } = user;
  return safe;
}

export function createUser(store, input) {
  const email = String(input?.email || "").toLowerCase();
  if (!email.includes("@")) throw new Error("valid email is required");
  if ([...store.users.values()].some((user) => user.email === email)) throw new Error("email already exists");
  const user = { id: randomUUID(), email, name: input.name || email, role: input.role || "user", passwordHash: hashPassword(input.password) };
  store.users.set(user.id, user);
  return publicUser(user);
}

export function authenticateUser(store, email, password) {
  const user = [...store.users.values()].find((candidate) => candidate.email === String(email || "").toLowerCase());
  if (!user || !verifyPassword(password, user.passwordHash)) throw new Error("invalid credentials");
  const session = createSession(user);
  store.sessions.set(session.token, session);
  return { session, user: publicUser(user) };
}

export function createProject(store, ownerId, input) {
  if (!store.users.has(ownerId)) throw new Error("owner not found");
  const title = String(input?.title || "").trim();
  if (!title) throw new Error("title is required");
  const project = { id: randomUUID(), ownerId, title, status: input.status || "active" };
  store.projects.set(project.id, project);
  return { ...project };
}

export function listProjects(store, ownerId) {
  return [...store.projects.values()].filter((project) => project.ownerId === ownerId).map((project) => ({ ...project }));
}

export function updateProject(store, ownerId, projectId, patch) {
  const project = store.projects.get(projectId);
  if (!project || project.ownerId !== ownerId) throw new Error("project not found");
  const updated = { ...project, ...patch, id: project.id, ownerId };
  store.projects.set(project.id, updated);
  return { ...updated };
}

export function deleteProject(store, ownerId, projectId) {
  const project = store.projects.get(projectId);
  if (!project || project.ownerId !== ownerId) throw new Error("project not found");
  store.projects.delete(projectId);
  return { deleted: true, id: projectId };
}