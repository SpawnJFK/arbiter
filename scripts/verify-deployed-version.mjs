#!/usr/bin/env node
/**
 * npm run verify:deployed: exit 0 when the deployed API is healthy and reports the same
 * commit as the expected one. Exit 1 otherwise, with both values printed.
 *
 *   npm run verify:deployed                                  (URL from hyperpower.json shipped.staging.apiUrl)
 *   DEPLOY_VERIFY_URL=https://api.<domain> npm run verify:deployed
 *   EXPECTED_GIT_SHA=<sha> npm run verify:deployed           (check a specific commit)
 *
 * Reads GET /healthz. Today it returns { ok: true } only; P02 adds `commit` (from an
 * ARBITER_GIT_COMMIT build arg) so this script can compare it. Until then it reports the
 * deployed commit as unknown and exits 1. No SSH and no secrets needed.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";

function configuredUrl() {
  if (process.env.DEPLOY_VERIFY_URL) return process.env.DEPLOY_VERIFY_URL;
  try {
    const hp = JSON.parse(fs.readFileSync("hyperpower.json", "utf8"));
    const url = hp?.shipped?.staging?.apiUrl;
    if (typeof url === "string" && url.startsWith("https://")) return url;
  } catch {
    /* fall through */
  }
  return null;
}

function gitHead() {
  const r = spawnSync("git", ["rev-parse", "HEAD"], { encoding: "utf8", windowsHide: true, shell: false });
  return r.status === 0 ? r.stdout.trim() : "";
}

const configured = configuredUrl();
if (!configured) {
  console.error("verify-deployed-version: nothing deployed yet (hyperpower.json shipped.staging.apiUrl is null and DEPLOY_VERIFY_URL is unset)");
  process.exit(1);
}
const base = configured.replace(/\/$/, "");
const expected = (process.env.EXPECTED_GIT_SHA || gitHead()).trim();
if (!expected) {
  console.error("verify-deployed-version: no expected commit (not a git checkout and EXPECTED_GIT_SHA unset)");
  process.exit(1);
}

let health;
try {
  const res = await fetch(`${base}/healthz`, { headers: { "cache-control": "no-cache" }, signal: AbortSignal.timeout(20_000) });
  health = { status: res.status, body: await res.json().catch(() => null) };
} catch (err) {
  console.error(`verify-deployed-version: ${base}/healthz unreachable: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
}

const deployed = String(health.body?.commit ?? "unknown");
const healthOk = health.status === 200 && health.body?.ok === true;
const short = (s) => s.slice(0, 12);
const match =
  deployed !== "unknown" &&
  deployed.length >= 7 &&
  (expected.startsWith(deployed) || deployed.startsWith(expected) || short(deployed) === short(expected));

const report = { url: base, expectedCommit: expected, deployedCommit: deployed, healthStatus: health.status, healthOk, match };

if (match && healthOk) {
  console.log(JSON.stringify({ ok: true, ...report }));
  process.exit(0);
}
if (deployed === "unknown") {
  console.error("verify-deployed-version: deployed commit is unknown; /healthz must return `commit` (P02 scope item)");
}
console.error(`verify-deployed-version: MISMATCH or unhealthy: expected ${short(expected)}, deployed ${short(deployed)}, health ${health.status}`);
console.error(JSON.stringify(report));
process.exit(1);
