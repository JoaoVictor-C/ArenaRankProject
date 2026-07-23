/**
 * Rating-engine parity gate — runs both engines on the shared fixtures and fails
 * if the base Plackett-Luce + CR identity diverge beyond tolerance.
 *
 *   node parity/compare.mjs            # tol from fixtures.json (or $PARITY_TOL)
 *
 * Spawns `python parity/run_py.py` (needs `arena.rating` importable — `pip install
 * ./backend`) and `npx tsx parity/run_ts.mts` (needs root `npm install`), captures
 * their JSON, and diffs crDelta / crAfter / muAfter / sigmaAfter per player.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const fixturesPath = join(here, "fixtures.json");
const fixtures = JSON.parse(readFileSync(fixturesPath, "utf-8"));
const tol = Number(process.env.PARITY_TOL ?? fixtures.tolerance ?? 1e-6);
const onWindows = process.platform === "win32";

function runEngine(cmd, args, label) {
  const r = spawnSync(cmd, [...args, fixturesPath], { encoding: "utf-8", shell: onWindows });
  if (r.status !== 0) {
    console.error(`[parity] ${label} runner failed (exit ${r.status}):\n${r.stderr || r.stdout}`);
    process.exit(2);
  }
  try {
    return JSON.parse(r.stdout);
  } catch {
    console.error(`[parity] ${label} produced non-JSON output:\n${r.stdout}\n${r.stderr}`);
    process.exit(2);
  }
}

const py = runEngine("python", [join(here, "run_py.py")], "python");
const ts = runEngine("npx", ["tsx", join(here, "run_ts.mts")], "typescript");

const indexBy = (payload) =>
  Object.fromEntries(payload.results.map((r) => [`${r.matchId}|${r.playerId}`, r]));
const A = indexBy(py);
const B = indexBy(ts);
const keys = new Set([...Object.keys(A), ...Object.keys(B)]);
const fields = ["crDelta", "crAfter", "muAfter", "sigmaAfter"];

let worst = 0;
let fails = 0;
let missing = 0;
for (const k of keys) {
  if (!A[k] || !B[k]) {
    console.error(`[parity] MISSING ${k} (py=${Boolean(A[k])} ts=${Boolean(B[k])})`);
    missing += 1;
    continue;
  }
  for (const f of fields) {
    const d = Math.abs(A[k][f] - B[k][f]);
    if (d > worst) worst = d;
    if (d > tol) {
      fails += 1;
      console.error(`[parity] DIVERGE ${k}.${f}: py=${A[k][f]} ts=${B[k][f]} Δ=${d.toExponential(3)}`);
    }
  }
}

console.log(
  `[parity] players=${keys.size} fields=${fields.join(",")} tol=${tol} ` +
    `worstΔ=${worst.toExponential(3)} fails=${fails} missing=${missing}`,
);

if (fails || missing) {
  console.error("[parity] FAIL — engines diverged beyond tolerance (or roster mismatch).");
  process.exit(1);
}
console.log("[parity] PASS — base Plackett-Luce + CR identity match within tolerance.");
