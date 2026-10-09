#!/usr/bin/env node
/**
 * Pre-push: warn when the live Beads export differs from the committed
 * .beads/issues.jsonl, so the issue graph does not silently stay on one
 * machine. Soft and loud: always exit 0.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const committedPath = path.join(root, ".beads", "issues.jsonl");

function findBd() {
  for (const name of ["bd.exe", "bd"]) {
    const pinned = path.join(root, ".hyperpower", "tools", "bin", name);
    if (fs.existsSync(pinned)) return pinned;
  }
  const finder = process.platform === "win32" ? "where" : "which";
  const which = spawnSync(finder, ["bd"], { encoding: "utf8", windowsHide: true, shell: false });
  return which.status === 0 && which.stdout?.trim() ? "bd" : null;
}

function normalizeJsonl(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.stringify(JSON.parse(line)))
    .join("\n");
}

function warn(message) {
  process.stderr.write(`${message}\n`);
  process.exit(0);
}

const bd = findBd();
if (!bd) {
  warn("[beads] pre-push: bd not installed, skipping export staleness check (install per docs/runbooks/bootstrap-fresh-clone.md)");
}

if (!fs.existsSync(committedPath)) {
  warn("[beads] pre-push: WARNING, .beads/issues.jsonl is missing; run `bd export -o .beads/issues.jsonl` and commit it");
}

const tmp = path.join(os.tmpdir(), `beads-export-${process.pid}-${Date.now()}.jsonl`);
const ex = spawnSync(bd, ["export", "-o", tmp], { cwd: root, encoding: "utf8", windowsHide: true, shell: false });

if (ex.status !== 0) {
  try {
    fs.unlinkSync(tmp);
  } catch {
    /* nothing to clean */
  }
  warn(`[beads] pre-push: bd export failed (exit ${ex.status ?? "?"}): ${(ex.stderr || ex.stdout || "").trim()}`);
}

let differs = false;
let compareError = null;
try {
  differs = normalizeJsonl(fs.readFileSync(tmp, "utf8")) !== normalizeJsonl(fs.readFileSync(committedPath, "utf8"));
} catch (err) {
  compareError = err instanceof Error ? err.message : String(err);
}
try {
  fs.unlinkSync(tmp);
} catch {
  /* nothing to clean */
}
if (compareError) {
  warn(`[beads] pre-push: could not compare exports: ${compareError}`);
}

if (differs) {
  warn(
    "[beads] pre-push: WARNING, live Beads export differs from committed .beads/issues.jsonl\n" +
      "  Fix: bd export -o .beads/issues.jsonl, then commit .beads/issues.jsonl\n" +
      "  Push continues (soft guard).",
  );
}

warn("[beads] pre-push: export in sync");
