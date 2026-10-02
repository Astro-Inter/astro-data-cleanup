import { DurableObject } from "cloudflare:workers";
import { createCleanupPorts, type CleanupEnv } from "./connectors.ts";
import { runCleanup, type CleanupJob } from "./cleanup.ts";
import { cleanupJobForSchedule, cleanupSchedules } from "./schedule.ts";

type RunState = {
  job: CleanupJob;
  status: "success" | "failed";
  dry_run: boolean;
  started_at: string;
  finished_at: string;
  analyzed?: number;
  candidates?: number;
  removed?: number;
  related_removed?: number;
  errors?: number;
  cutoff?: string | null;
  error_code?: string;
  error_type?: string;
};

interface Env extends CleanupEnv {
  COORDINATOR: DurableObjectNamespace<CleanupCoordinator>;
  API_ENABLED?: string;
  JOBS_ENABLED?: string;
  JOBS_TOKEN?: string;
  DRY_RUN?: string;
}

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store" } });
}

function safeErrorCode(error: unknown): string {
  if (error instanceof Error && /^(?:missing_[a-z_]+|(?:firebase|postgres|mongo|mongodb|qdrant)_[a-z_]+)$/u.test(error.message)) {
    return error.message;
  }
  if (error instanceof Error && error.name === "MongoNetworkError") return "mongo_network_failed";
  if (error instanceof Error && error.name === "MongoServerSelectionError") return "mongo_network_failed";
  return "unexpected_error";
}

function authorized(request: Request, env: Env): boolean {
  const token = env.JOBS_TOKEN;
  return typeof token === "string" && token.length >= 32
    && request.headers.get("Authorization") === `Bearer ${token}`;
}

function parseDryRun(url: URL): boolean | null {
  const value = url.searchParams.get("dry_run");
  if (value === null || value === "true") return true;
  if (value === "false") return false;
  return null;
}

function coordinator(env: Env, job: CleanupJob): DurableObjectStub<CleanupCoordinator> {
  return env.COORDINATOR.getByName(job);
}

export class CleanupCoordinator extends DurableObject<Env> {
  async runJob(job: CleanupJob, dryRun: boolean): Promise<RunState> {
    const startedAt = new Date().toISOString();
    const lock = await this.ctx.storage.transaction(async (txn) => {
      const runningSince = await txn.get<string>("running");
      if (runningSince && Date.now() - Date.parse(runningSince) < 20 * 60_000) return false;
      await txn.put("running", startedAt);
      return true;
    });
    if (!lock) {
      return {
        job, status: "failed", dry_run: dryRun,
        started_at: startedAt, finished_at: new Date().toISOString(),
        errors: 1,
      };
    }
    try {
      if (this.env.JOBS_ENABLED !== "true") throw new Error("jobs_disabled");
      if (!dryRun && this.env.DRY_RUN !== "false") throw new Error("dry_run_protected");
      const created = await createCleanupPorts(this.env);
      let summary;
      try { summary = await runCleanup(job, created.ports, dryRun); }
      finally { await created.close(); }
      const result: RunState = {
        ...summary,
        status: summary.errors ? "failed" : "success",
        started_at: startedAt,
        finished_at: new Date().toISOString(),
      };
      await this.ctx.storage.put("latest", result);
      return result;
    } catch (error) {
      const errorCode = safeErrorCode(error);
      const result: RunState = {
        job, status: "failed", dry_run: dryRun,
        started_at: startedAt, finished_at: new Date().toISOString(), errors: 1,
        error_code: errorCode,
        error_type: error instanceof Error ? error.name : typeof error,
      };
      await this.ctx.storage.put("latest", result);
      console.error(JSON.stringify({ event: "cleanup_failed", job, dry_run: dryRun, error_code: errorCode }));
      return result;
    } finally {
      await this.ctx.storage.delete("running");
    }
  }

  async getLatest(): Promise<RunState | null> {
    return await this.ctx.storage.get<RunState>("latest") ?? null;
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return json({ service: "astro-data-cleanup", status: "ok" });
    }
    if (env.API_ENABLED !== "true") return json({ error: "api_inactive" }, 503);
    if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);

    if (url.pathname === "/status" && request.method === "GET") {
      const latest = await Promise.all(
        Object.values(cleanupSchedules()).map((job) => coordinator(env, job).getLatest()),
      );
      return json({
        service: "astro-data-cleanup",
        enabled: env.JOBS_ENABLED === "true",
        dry_run: env.DRY_RUN !== "false",
        schedules: cleanupSchedules(),
        latest: Object.fromEntries(Object.values(cleanupSchedules()).map((job, index) => [job, latest[index]])),
      });
    }

    const match = url.pathname.match(/^\/jobs\/([a-z-]+)$/u);
    const job = match?.[1] as CleanupJob | undefined;
    if (request.method !== "POST" || !job || !Object.values(cleanupSchedules()).includes(job)) {
      return json({ error: "not_found" }, 404);
    }
    const dryRun = parseDryRun(url);
    if (dryRun === null) return json({ error: "invalid_dry_run" }, 400);
    if (!dryRun && (env.JOBS_ENABLED !== "true" || env.DRY_RUN !== "false")) {
      return json({ error: "destructive_run_disabled" }, 503);
    }
    const result = await coordinator(env, job).runJob(job, dryRun);
    return json(result, result.status === "success" ? 200 : 500);
  },

  async scheduled(event: ScheduledController, env: Env): Promise<void> {
    const job = cleanupJobForSchedule(event.cron, event.scheduledTime);
    if (env.JOBS_ENABLED !== "true") {
      console.log(JSON.stringify({ event: "cleanup_cron_inactive", job }));
      return;
    }
    const dryRun = env.DRY_RUN !== "false";
    const result = await coordinator(env, job).runJob(job, dryRun);
    console.log(JSON.stringify({ event: "cleanup_job_finished", ...result }));
  },
} satisfies ExportedHandler<Env>;
