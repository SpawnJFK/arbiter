#!/usr/bin/env node
/**
 * Pre-push: make sure the Graphify index matches HEAD (structural freshness).
 * Soft and loud: never blocks a push (always exit 0). `npm run hp -- doctor`
 * runs this same script and treats a "skipping" line as BROKEN, so a missing
 * Graphify install cannot hide behind a passing push.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = path.join(root, "graphify-out", "manifest.json");

function onPath(name) {
  const finder = process.platform === "win32" ? "where" : "which";
  const r = spawnSync(finder, [name], { encoding: "utf8", windowsHide: true, shell: false });
  return r.status === 0 && r.stdout?.trim() ? r.stdout.trim().split(/\r?\n/)[0] : null;
}

function resolveGraphify() {
  const fromEnv = process.env.GIT_HOOK_GRAPHIFY?.trim();
  if (fromEnv && fs.existsSync(fromEnv)) return fromEnv;
  for (const name of ["graphify.exe", "graphify"]) {
    const pinned = path.join(root, ".hyperpower", "tools", "bin", name);
    if (fs.existsSync(pinned)) return pinned;
  }
  return onPath("graphify");
}

function runGraphify(graphify, args, opts = {}) {
  return spawnSync(graphify, args, {
    cwd: root,
    encoding: "utf8",
    stdio: opts.stdio ?? "pipe",
    windowsHide: true,
    shell: false,
  });
}

function softExit(message) {
  if (message) process.stderr.write(`${message}\n`);
  process.exit(0);
}

function gitHead() {
  const r = spawnSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8", windowsHide: true, shell: false });
  return r.status === 0 ? r.stdout.trim() : "";
}

const graphify = resolveGraphify();
if (!gitHead()) {
  softExit("[graphify] pre-push: could not read HEAD, allowing push");
}
if (!graphify) {
  softExit("[graphify] pre-push: graphify not installed, skipping index check");
}

if (!fs.existsSync(manifestPath)) {
  process.stderr.write("[graphify] pre-push: no graph manifest, running extract\n");
  const ex = runGraphify(graphify, ["extract", ".", "--code-only", "--no-viz"], { stdio: "inherit" });
  if (ex.status !== 0) {
    softExit("[graphify] pre-push: extract failed, allowing push (soft guard)");
  }
}

const check = runGraphify(graphify, ["check-update", "."]);
const out = `${check.stdout ?? ""}${check.stderr ?? ""}`;
if (/needs.?update|stale|out.?of.?date/i.test(out)) {
  process.stderr.write("[graphify] pre-push: index stale, running update\n");
  const up = runGraphify(graphify, ["update", ".", "--no-viz"], { stdio: "inherit" });
  if (up.status !== 0) {
    softExit("[graphify] pre-push: update failed, allowing push (soft guard)");
  }
}

softExit("[graphify] pre-push: index fresh, continuing push");
