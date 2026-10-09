#!/usr/bin/env node
// Pre-commit checks on STAGED files only. Soft and loud: every finding is printed with the fix,
// and the script always exits 0, because a guard that blocks work gets bypassed.
// `npm run verify` (and CI) are the hard checks.
//
//   [ruff]    staged .py under services/api: ruff check + ruff format --check (API venv)
//   [i18n]    staged files under apps/web/src or apps/web/messages: npm run i18n:check
//   [env]     a staged env file other than .env.example
//   [dash]    an em dash in an added line outside test fixtures and vendored skills (.cursor/skills)
//   [secrets] Betterleaks over the staged diff, when .hyperpower/tools/bin has it

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { apiPython, root } from "./lib/proc.mjs";

function say(line) {
  process.stderr.write(`${line}\n`);
}

function git(args) {
  return spawnSync("git", args, { cwd: root, encoding: "utf8", windowsHide: true, shell: false, maxBuffer: 64 * 1024 * 1024 });
}

const staged = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]);
if (staged.status !== 0) {
  say("[githook] pre-commit: could not list staged files, checks skipped");
  process.exit(0);
}
const files = staged.stdout.split("\0").filter(Boolean);
if (files.length === 0) {
  say("[githook] pre-commit: no staged files");
  process.exit(0);
}
say(`[githook] pre-commit: checking ${files.length} staged file(s)`);

// [ruff]
const py = files.filter((f) => f.startsWith("services/api/") && f.endsWith(".py") && fs.existsSync(path.join(root, f)));
if (py.length) {
  const python = apiPython();
  if (!python) {
    say("[ruff] pre-commit skipped: services/api/.venv missing (bootstrap runbook step 2)");
  } else {
    const rel = py.map((f) => f.slice("services/api/".length));
    const cwd = path.join(root, "services", "api");
    const check = spawnSync(python, ["-m", "ruff", "check", ...rel], { cwd, encoding: "utf8", windowsHide: true });
    const format = spawnSync(python, ["-m", "ruff", "format", "--check", ...rel], { cwd, encoding: "utf8", windowsHide: true });
    if (check.status === 0 && format.status === 0) {
      say(`[ruff] pre-commit: ${py.length} staged Python file(s) clean`);
    } else {
      say(`[ruff] pre-commit: WARNING, ruff found problems in staged Python files`);
      say(`${check.stdout ?? ""}${check.stderr ?? ""}${format.stdout ?? ""}${format.stderr ?? ""}`.trim());
      say("[ruff] Fix: make fmt (or ruff format + ruff check --fix in services/api). Commit continues (soft guard).");
    }
  }
}

// [i18n]
if (files.some((f) => f.startsWith("apps/web/src/") || f.startsWith("apps/web/messages/"))) {
  const checker = path.join(root, "apps", "web", "scripts", "i18n-check.mjs");
  if (!fs.existsSync(checker)) {
    say("[i18n] pre-commit skipped: missing apps/web/scripts/i18n-check.mjs");
  } else {
    const r = spawnSync(process.execPath, [checker], { cwd: path.join(root, "apps", "web"), encoding: "utf8", windowsHide: true });
    if (r.status === 0) {
      say("[i18n] pre-commit: message catalog matches the source");
    } else {
      say("[i18n] pre-commit: WARNING, i18n:check failed");
      say(`${r.stdout ?? ""}${r.stderr ?? ""}`.trim());
      say("[i18n] Fix: every UI string goes through t() with a key in apps/web/messages/en.json. Commit continues (soft guard).");
    }
  }
}

// [env]
const envFiles = files.filter((f) => /(^|\/)\.env($|\.)/.test(f) && !f.endsWith(".env.example"));
if (envFiles.length) {
  say(`[env] pre-commit: WARNING, env file staged: ${envFiles.join(", ")}`);
  say("[env] Fix: git restore --staged <file>. Keys only via ARBITER_* env vars, never in git. Commit continues (soft guard).");
}

// [dash]
const diff = git(["diff", "--cached", "-U0", "--no-color", "--", ".", ":(exclude)services/api/tests", ":(exclude)apps/web/e2e", ":(exclude).cursor/skills"]);
if (diff.status === 0) {
  let current = "";
  const hits = [];
  for (const line of diff.stdout.split(/\r?\n/)) {
    if (line.startsWith("+++ b/")) current = line.slice(6);
    else if (line.startsWith("+") && !line.startsWith("+++") && line.includes("\u2014")) hits.push(current);
  }
  if (hits.length) {
    say(`[dash] pre-commit: WARNING, em dash in added lines of: ${[...new Set(hits)].join(", ")}`);
    say("[dash] Fix: use a colon, comma or parentheses. Commit continues (soft guard).");
  }
}

// [secrets]
const leaks = ["betterleaks.exe", "betterleaks"].map((n) => path.join(root, ".hyperpower", "tools", "bin", n)).find((p) => fs.existsSync(p));
if (!leaks) {
  say("[secrets] pre-commit skipped: Betterleaks not installed at .hyperpower/tools/bin (bootstrap runbook step 5)");
} else {
  // Flags follow the gitleaks 8 pre-commit form; P00 confirms them against the pinned 1.9.0 help output.
  const r = spawnSync(leaks, ["git", "--pre-commit", "--staged", "--redact", "--no-banner"], {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
  });
  const out = `${r.stdout ?? ""}${r.stderr ?? ""}`.trim();
  if (r.status === 0) {
    say("[secrets] pre-commit: no secrets in the staged diff");
  } else if (/unknown (flag|command)|flag provided but not defined/i.test(out)) {
    say("[secrets] pre-commit: WARNING, Betterleaks rejected the flags; fix scripts/githook-pre-commit.mjs to the pinned CLI");
    say(out);
  } else {
    say("[secrets] pre-commit: WARNING, Betterleaks reports a possible secret in the staged diff");
    say(out);
    say("[secrets] Fix: unstage it, move the value to an ARBITER_* env var, rotate the key if it was ever pushed. Commit continues (soft guard).");
  }
}

process.exit(0);
