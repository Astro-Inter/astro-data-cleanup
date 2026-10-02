import assert from "node:assert/strict";
import { test } from "node:test";
import { CLEANUP_CRON, cleanupJobForSchedule, cleanupSchedules } from "./schedule.ts";

test("one combined Cron Trigger preserves the three original hourly schedules", () => {
  assert.equal(CLEANUP_CRON, "5,25,45 * * * *");
  assert.deepEqual(cleanupSchedules(), {
    "5 * * * *": "firebase-orphan-users",
    "25 * * * *": "chatbot-sessions",
    "45 * * * *": "old-conversations",
  });
  assert.equal(cleanupJobForSchedule(CLEANUP_CRON, Date.UTC(2026, 0, 1, 0, 5)), "firebase-orphan-users");
  assert.equal(cleanupJobForSchedule(CLEANUP_CRON, Date.UTC(2026, 0, 1, 0, 25)), "chatbot-sessions");
  assert.equal(cleanupJobForSchedule(CLEANUP_CRON, Date.UTC(2026, 0, 1, 0, 45)), "old-conversations");
  assert.throws(() => cleanupJobForSchedule(CLEANUP_CRON, Date.UTC(2026, 0, 1, 0, 50)), /unexpected_cron_trigger/);
  assert.throws(() => cleanupJobForSchedule("* * * * *", Date.now()), /unexpected_cron_trigger/);
});
