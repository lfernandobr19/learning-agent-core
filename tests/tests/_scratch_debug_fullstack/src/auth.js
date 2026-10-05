import { createHash, randomUUID } from "node:crypto";

export function hashPassword(password, salt = "ravenna-local") {
  if (typeof password !== "string" || password.length < 8) throw new Error("password must have at least 8 characters");
  return createHash("sha256").update(`${salt}:${password}`).digest("hex");
}

export function verifyPassword(password, passwordHash, salt = "ravenna-local") {
  return hashPassword(password, salt) === passwordHash;
}

export function createSession(user) {
  if (!user?.id) throw new Error("user is required");
  return { token: randomUUID(), userId: user.id, role: user.role || "user" };
}