import assert from "node:assert/strict";
import { test } from "node:test";
import { calendarYearsBefore, runCleanup, type CleanupPorts } from "./cleanup.ts";

function ports(overrides: Partial<CleanupPorts> = {}): CleanupPorts {
  return {
    accounts: {
      async listFirebaseUids() { return new Set(["linked"]); },
      async firebaseUidExists(uid) { return uid === "linked"; },
    },
    firebase: {
      async *listUsers() { yield { uid: "linked" }; yield { uid: "orphan" }; },
      async deleteUser() {},
    },
    sessions: {
      async *listExpired(cutoff) { yield { id: "session", startedAt: new Date(cutoff.getTime() - 1) }; },
      async isExpired() { return true; },
      async deleteExpired() { return true; },
    },
    messages: {
      async *listExpired(cutoff) { yield { id: "message", sentAt: new Date(cutoff.getTime() - 1) }; },
      async isExpired() { return true; },
      async deleteExpired() { return true; },
    },
    vectors: {
      async countBySessionId() { return 2; },
      async deleteBySessionId() { return 2; },
    },
    ...overrides,
  };
}

test("calendar retention clamps leap day in UTC", () => {
  assert.equal(calendarYearsBefore(new Date("2024-02-29T08:30:00Z"), 2).toISOString(), "2022-02-28T08:30:00.000Z");
});

test("Firebase orphan dry-run revalidates candidates and never deletes", async () => {
  let deleted = 0;
  const fake = ports({
    firebase: {
      async *listUsers() { yield { uid: "linked" }; yield { uid: "orphan" }; yield { uid: "restored" }; },
      async deleteUser() { deleted++; },
    },
    accounts: {
      async listFirebaseUids() { return new Set(["linked"]); },
      async firebaseUidExists(uid) { return uid === "restored"; },
    },
  });
  const summary = await runCleanup("firebase-orphan-users", fake, true);
  assert.deepEqual({ analyzed: summary.analyzed, candidates: summary.candidates, removed: summary.removed }, { analyzed: 3, candidates: 1, removed: 0 });
  assert.equal(deleted, 0);
});

test("session dry-run counts linked vectors and does not delete either service", async () => {
  let mongoDeleted = 0;
  let qdrantDeleted = 0;
  const base = ports();
  const fake = {
    ...base,
    sessions: { ...base.sessions, async deleteExpired() { mongoDeleted++; return true; } },
    vectors: { ...base.vectors, async deleteBySessionId() { qdrantDeleted++; return 2; } },
  };
  const summary = await runCleanup("chatbot-sessions", fake, true, new Date("2026-09-20T00:00:00Z"));
  assert.equal(summary.candidates, 1);
  assert.equal(summary.related_removed, 2);
  assert.equal(mongoDeleted + qdrantDeleted, 0);
});

test("real session cleanup removes Qdrant vectors before Mongo document", async () => {
  const events: string[] = [];
  const base = ports();
  const fake = {
    ...base,
    sessions: { ...base.sessions, async deleteExpired() { events.push("mongo"); return true; } },
    vectors: { ...base.vectors, async deleteBySessionId() { events.push("qdrant"); return 2; } },
  };
  const summary = await runCleanup("chatbot-sessions", fake, false, new Date("2026-09-20T00:00:00Z"));
  assert.deepEqual(events, ["qdrant", "mongo"]);
  assert.equal(summary.removed, 1);
  assert.equal(summary.related_removed, 2);
});

test("old conversation dry-run reports but never removes", async () => {
  let deleted = 0;
  const base = ports();
  const fake = {
    ...base,
    messages: { ...base.messages, async deleteExpired() { deleted++; return true; } },
  };
  const summary = await runCleanup("old-conversations", fake, true, new Date("2026-09-20T00:00:00Z"));
  assert.equal(summary.candidates, 1);
  assert.equal(summary.removed, 0);
  assert.equal(deleted, 0);
});

test("single item deletion errors are counted without aborting the whole cleanup", async () => {
  const base = ports();
  const fake = {
    ...base,
    messages: {
      async *listExpired(cutoff: Date) {
        yield { id: "one", sentAt: new Date(cutoff.getTime() - 1) };
        yield { id: "two", sentAt: new Date(cutoff.getTime() - 1) };
      },
      async isExpired() { return true; },
      async deleteExpired(message: { id: string }) { if (message.id === "one") throw new Error("db"); return true; },
    },
  };
  const summary = await runCleanup("old-conversations", fake, false);
  assert.equal(summary.errors, 1);
  assert.equal(summary.removed, 1);
});
