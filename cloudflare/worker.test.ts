import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { type CleanupCoordinator } from "./worker.ts";

const token = "x".repeat(48);
function env(overrides: Record<string, unknown> = {}) {
  const calls: unknown[][] = [];
  const latest = { job: "old-conversations", status: "success", dry_run: true };
  const stub = {
    async getLatest() { return latest; },
    async runJob(...args: unknown[]) { calls.push(args); return latest; },
  };
  const base = {
    API_ENABLED: "true", JOBS_ENABLED: "true", JOBS_TOKEN: token, DRY_RUN: "true",
    COORDINATOR: { getByName() { return stub; } },
  };
  return { value: { ...base, ...overrides } as never, calls };
}

test("health is public and contains no configuration", async () => {
  const response = await worker.fetch!(new Request("https://worker.example/health"), env().value);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { service: "astro-data-cleanup", status: "ok" });
});

test("status and job endpoints require bearer authorization", async () => {
  const context = env();
  assert.equal((await worker.fetch!(new Request("https://worker.example/status"), context.value)).status, 401);
  assert.equal((await worker.fetch!(new Request("https://worker.example/jobs/old-conversations", { method: "POST" }), context.value)).status, 401);
});

test("manual jobs default to dry-run", async () => {
  const context = env();
  const response = await worker.fetch!(new Request("https://worker.example/jobs/old-conversations", {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  }), context.value);
  assert.equal(response.status, 200);
  assert.deepEqual(context.calls, [["old-conversations", true]]);
});

test("production deletion cannot be requested while DRY_RUN is set", async () => {
  const context = env();
  const response = await worker.fetch!(new Request("https://worker.example/jobs/old-conversations?dry_run=false", {
    method: "POST", headers: { Authorization: `Bearer ${token}` },
  }), context.value);
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "destructive_run_disabled" });
  assert.equal(context.calls.length, 0);
});

test("scheduled cron maps each declared expression to exactly one job", async () => {
  const context = env();
  await worker.scheduled!({ cron: "25 * * * *", scheduledTime: Date.now() } as ScheduledController, context.value);
  assert.deepEqual(context.calls, [["chatbot-sessions", true]]);
  await assert.rejects(worker.scheduled!({ cron: "* * * * *", scheduledTime: Date.now() } as ScheduledController, context.value), /unexpected_cron_trigger/);
});

test("disabled jobs do not invoke the coordinator", async () => {
  const context = env({ JOBS_ENABLED: "false" });
  await worker.scheduled!({ cron: "50 3 * * SUN", scheduledTime: Date.now() } as ScheduledController, context.value);
  assert.equal(context.calls.length, 0);
});
