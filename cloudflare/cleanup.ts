import { observe, diagnostic } from "./diagnostics.ts";
import type { ObjectId } from "mongodb";

export type CleanupJob = "firebase-orphan-users" | "chatbot-sessions" | "old-conversations";

export type FirebaseUser = { uid: string };
export type ExpiredSession = { id: string; startedAt: Date };
export type MessageId = string | ObjectId;
export type ExpiredMessage = { id: MessageId; sentAt: Date };

export interface CleanupPorts {
  accounts: {
    listFirebaseUids(): Promise<Set<string>>;
    firebaseUidExists(uid: string): Promise<boolean>;
  };
  firebase: {
    listUsers(): AsyncIterable<FirebaseUser>;
    deleteUser(uid: string): Promise<void>;
  };
  sessions: {
    listExpired(cutoff: Date): AsyncIterable<ExpiredSession>;
    isExpired(id: string, cutoff: Date): Promise<boolean>;
    deleteExpired(session: ExpiredSession, cutoff: Date): Promise<boolean>;
  };
  messages: {
    listExpired(cutoff: Date): AsyncIterable<ExpiredMessage>;
    isExpired(id: MessageId, cutoff: Date): Promise<boolean>;
    deleteExpired(message: ExpiredMessage, cutoff: Date): Promise<boolean>;
  };
  vectors: {
    countBySessionId(id: string): Promise<number>;
    deleteBySessionId(id: string): Promise<number>;
  };
}

export type CleanupSummary = {
  job: CleanupJob;
  dry_run: boolean;
  analyzed: number;
  candidates: number;
  removed: number;
  related_removed: number;
  errors: number;
  cutoff: string | null;
};

export function calendarYearsBefore(moment: Date, years: number): Date {
  if (!Number.isInteger(years) || years < 1 || !Number.isFinite(moment.getTime())) {
    throw new Error("invalid_retention_clock");
  }
  const result = new Date(moment);
  const targetYear = result.getUTCFullYear() - years;
  const month = result.getUTCMonth();
  const day = result.getUTCDate();
  result.setUTCDate(1);
  result.setUTCFullYear(targetYear);
  result.setUTCMonth(month);
  const lastDay = new Date(Date.UTC(targetYear, month + 1, 0)).getUTCDate();
  result.setUTCDate(Math.min(day, lastDay));
  return result;
}

export async function runCleanup(
  job: CleanupJob,
  ports: CleanupPorts,
  dryRun: boolean,
  now: Date = new Date(),
  runId?: string,
): Promise<CleanupSummary> {
  const summary: CleanupSummary = {
    job, dry_run: dryRun, analyzed: 0, candidates: 0, removed: 0,
    related_removed: 0, errors: 0, cutoff: null,
  };

  if (job === "firebase-orphan-users") {
    const databaseUids = await ports.accounts.listFirebaseUids();
    for await (const user of ports.firebase.listUsers()) {
      summary.analyzed++;
      if (databaseUids.has(user.uid)) continue;
      if (await ports.accounts.firebaseUidExists(user.uid)) continue;
      summary.candidates++;
      if (dryRun) continue;
      try {
        await observe("delete_user", "firebase", () => ports.firebase.deleteUser(user.uid));
        summary.removed++;
      } catch (error) {
        console.error(JSON.stringify({ event: "cleanup_item_failed", job, run_id: runId, ...diagnostic(error) }));
        summary.errors++;
      }
    }
    return summary;
  }

  const years = job === "chatbot-sessions" ? 1 : 2;
  const cutoff = calendarYearsBefore(now, years);
  summary.cutoff = cutoff.toISOString();
  if (job === "chatbot-sessions") {
    for await (const session of ports.sessions.listExpired(cutoff)) {
      summary.analyzed++;
      if (!(await ports.sessions.isExpired(session.id, cutoff))) continue;
      summary.candidates++;
      if (dryRun) {
        try { summary.related_removed += await observe("count_vectors", "qdrant", () => ports.vectors.countBySessionId(session.id)); }
        catch (error) { console.error(JSON.stringify({ event: "cleanup_vector_count_failed", job, run_id: runId, ...diagnostic(error) })); summary.errors++; }
        continue;
      }
      try {
        const vectorCount = await observe("delete_vectors", "qdrant", () => ports.vectors.deleteBySessionId(session.id));
        summary.related_removed += vectorCount;
        if (await observe("delete_session", "mongodb", () => ports.sessions.deleteExpired(session, cutoff))) summary.removed++;
        else summary.errors++;
      } catch (error) {
        console.error(JSON.stringify({ event: "cleanup_item_failed", job, run_id: runId, ...diagnostic(error) }));
        summary.errors++;
      }
    }
    return summary;
  }

  for await (const message of ports.messages.listExpired(cutoff)) {
    summary.analyzed++;
    if (!(await ports.messages.isExpired(message.id, cutoff))) continue;
    summary.candidates++;
    if (dryRun) continue;
    try {
      if (await observe("delete_message", "mongodb", () => ports.messages.deleteExpired(message, cutoff))) summary.removed++;
      else summary.errors++;
    } catch (error) {
      console.error(JSON.stringify({ event: "cleanup_item_failed", job, run_id: runId, ...diagnostic(error) }));
      summary.errors++;
    }
  }
  return summary;
}
