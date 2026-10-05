import { createStore, createUser, authenticateUser, createProject, listProjects } from "./store.js";

const store = createStore();
const user = createUser(store, { email: "owner@example.com", name: "Owner", password: "strongpass" });
const login = authenticateUser(store, "owner@example.com", "strongpass");
createProject(store, user.id, { title: "Launch Ravenna" });
console.log(JSON.stringify({ ok: true, userId: login.user.id, projects: listProjects(store, user.id).length }));