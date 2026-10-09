#!/usr/bin/env node
// npm run check:runtime: first step of npm run verify.
// Node major must equal .node-version (doctor checks the same against hyperpower.json),
// and the API venv's Python must match .python-version (doctor does not check Python).

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { apiPython, root } from "./lib/proc.mjs";

const problems = [];

const nodePin = fs.readFileSync(path.join(root, ".node-version"), "utf8").trim().replace(/^v/, "");
const nodeMajor = process.versions.node.split(".")[0];
if (nodeMajor !== nodePin.split(".")[0]) {
  problems.push(`Node ${process.versions.node} does not match .node-version ${nodePin} (fnm use reads .node-version)`);
}

const pyPin = fs.readFileSync(path.join(root, ".python-version"), "utf8").trim();
const py = apiPython();
if (!py) {
  problems.push("services/api/.venv is missing (P00 creates it with uv and Python " + pyPin + ")");
} else {
  const r = spawnSync(py, ["-c", "import sys; print('%d.%d' % sys.version_info[:2])"], {
    encoding: "utf8",
    windowsHide: true,
  });
  const got = (r.stdout ?? "").trim();
  if (r.status !== 0 || got !== pyPin) {
    problems.push(`API venv Python is ${got || "unreadable"}, .python-version pins ${pyPin}`);
  }
}

if (problems.length) {
  for (const p of problems) console.error(`[check:runtime] ${p}`);
  process.exit(1);
}
console.log(`[check:runtime] ok: Node ${process.versions.node} (pin ${nodePin}), API Python ${pyPin}`);
