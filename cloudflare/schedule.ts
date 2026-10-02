import type { CleanupJob } from "./cleanup.ts";

export const CLEANUP_CRON = "5,25,45 * * * *";
const CRON_MINUTE_TO_JOB: Record<number, CleanupJob> = {
  5: "firebase-orphan-users",
  25: "chatbot-sessions",
  45: "old-conversations",
};

export function cleanupJobForSchedule(cron: string, scheduledTime: number): CleanupJob {
  const job = cron === CLEANUP_CRON ? CRON_MINUTE_TO_JOB[new Date(scheduledTime).getUTCMinutes()] : undefined;
  if (!job) throw new Error("unexpected_cron_trigger");
  return job;
}

export function cleanupSchedules(): Record<string, CleanupJob> {
  return Object.fromEntries(Object.entries(CRON_MINUTE_TO_JOB).map(([minute, job]) => [`${minute} * * * *`, job]));
}
