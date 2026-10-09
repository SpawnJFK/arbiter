#!/usr/bin/env node
// npm run verify:e2e: runs apps/web/e2e/real-flow.mjs (journeys J-01..J-09 in ACCEPTANCE.md)
// against a RUNNING stack and maps its step lines to journey ids.
//
// Needs, before it starts (it checks and says what is missing, it does not start services):
//   API on API_URL (default http://localhost:8000, GET /healthz), the pipeline worker,
//   demo data (python -m arbiter.cli seed-demo), and the web app built WITHOUT
//   NEXT_PUBLIC_API_MOCK and started on BASE_URL (default http://localhost:3000).
//
// Output ends with one line per journey ("J-03 PASS") and, when all pass,
// "E2E JOURNEYS J-01..J-09 PASS". Evidence records use it as a `cli` verifier with
// expectOutputContains set to the journey line. No arguments: the core's cli verifier
// rewrites node arguments into paths.

import { spawn } from "node:child_process";
import path from "node:path";
import { apiPython, root } from "./lib/proc.mjs";

const API = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const BASE = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

// Each journey is proven when real-flow.mjs printed this step (it aborts on the first failure).
const JOURNEYS = [
  ["J-01", "quote shows 4 tiers"],
  ["J-02", "evidence PDF ok"],
  ["J-03", "full-tier job delivered after human review"],
  ["J-04", "blocked segment listed in Exceptions"],
  ["J-05", "applicant took a test:"],
  ["J-06", "admin sees reviewers and payouts"],
  ["J-07", "accounts, the pharma workflow and the new dashboard exist"],
  ["J-08", "client approved, job delivered"],
  ["J-09", "PM switched to Deutsch"],
];

async function reachable(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(10_000), redirect: "manual" });
    return res.status > 0 && res.status < 500;
  } catch {
    return false;
  }
}

const missing = [];
if (!(await reachable(`${API}/healthz`))) missing.push(`API not answering at ${API}/healthz (start it: make api, or uvicorn arbiter.api.app:app --port 8000 in services/api)`);
if (!(await reachable(`${BASE}/login`))) missing.push(`web not answering at ${BASE}/login (build without NEXT_PUBLIC_API_MOCK, then npm start -- -p 3000 in apps/web)`);
const py = process.env.PYTHON ?? apiPython();
if (!py) missing.push("services/api/.venv is missing (real-flow.mjs uses its python-docx to build a .docx fixture)");
if (missing.length) {
  for (const m of missing) console.error(`[verify:e2e] ${m}`);
  console.error("[verify:e2e] stack not running; nothing was tested");
  process.exit(2);
}

console.log(`[verify:e2e] running apps/web/e2e/real-flow.mjs against ${BASE} (API ${API}); one line per step`);
const t0 = Date.now();
const child = spawn(process.execPath, [path.join(root, "apps", "web", "e2e", "real-flow.mjs")], {
  cwd: path.join(root, "apps", "web"),
  env: { ...process.env, BASE_URL: BASE, PYTHON: py },
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
let out = "";
child.stdout.on("data", (c) => {
  out += c.toString();
  process.stdout.write(c);
});
child.stderr.on("data", (c) => {
  out += c.toString();
  process.stderr.write(c);
});
const beat = setInterval(() => {
  const done = JOURNEYS.filter(([, marker]) => out.includes(marker)).length;
  const s = Math.round((Date.now() - t0) / 1000);
  console.log(`[verify:e2e] ${done}/${JOURNEYS.length} journeys passed so far (${Math.round((done / JOURNEYS.length) * 100)}%), ${s}s elapsed`);
}, 30_000);

const code = await new Promise((resolve) => child.on("close", (c, sig) => resolve(c ?? (sig ? 1 : 0))));
clearInterval(beat);

let all = code === 0 && out.includes("E2E OK");
for (const [id, marker] of JOURNEYS) {
  const ok = out.includes(marker);
  if (!ok) all = false;
  console.log(`${id} ${ok ? "PASS" : "NOT REACHED"}`);
}
if (all) {
  console.log("E2E JOURNEYS J-01..J-09 PASS");
  process.exit(0);
}
console.error(`[verify:e2e] FAILED (real-flow.mjs exit ${code})`);
process.exit(code === 0 ? 1 : code);
