import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(readFileSync(join(root, "wrangler.jsonc"), "utf8"));
const hyperdrive = new Map((config.hyperdrive ?? []).map((entry) => [entry.binding, entry.id]));
const validId = (id) => typeof id === "string" && /^[a-f0-9]{32}$/iu.test(id) && !/^0+$/u.test(id);
const args = process.argv.slice(2);
const safe = config.account_id === "25eb8d3849be3adbff3678f4ec781804"
  && !Object.hasOwn(config, "limits")
  && config.observability?.enabled === false
  && config.preview_urls === false
  && config.vars?.API_ENABLED === "true"
  && config.vars?.JOBS_ENABLED === "true"
  && config.vars?.DRY_RUN === "true"
  && JSON.stringify(config.triggers?.crons) === JSON.stringify(["5,25,45 * * * *"])
  && (config.containers?.length ?? 0) === 0
  && config.durable_objects?.bindings?.length === 1
  && config.durable_objects.bindings[0].class_name === "CleanupCoordinator"
  && validId(hyperdrive.get("POSTGRES"));

if (!safe) {
  console.error("Deploy blocked: require Workers Free defaults, SQLite Durable Object only, hourly crons, DRY_RUN=true, and a valid Hyperdrive binding.");
  process.exit(1);
}

if (args.some((argument) => argument !== "--dry-run")) {
  console.error("Deploy blocked: only --dry-run may be passed to Wrangler.");
  process.exit(1);
}

const wrangler = join(root, "node_modules", "wrangler", "bin", "wrangler.js");
const result = spawnSync(process.execPath, [wrangler, "deploy", ...args], {
  cwd: root,
  env: process.env,
  stdio: "inherit",
});
process.exit(result.status ?? 1);
