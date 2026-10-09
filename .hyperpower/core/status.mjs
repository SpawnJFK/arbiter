#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { inside } from "./common.mjs";
import { displayName, loadProject, projectName, requiredTools } from "./project.mjs";
import { readLedger } from "./evidence.mjs";

/**
 * @param {string} [startDir]
 */
export function buildStatusReport(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const ledger = readLedger(startDir);

  const byTier = {};
  const byStatus = {};
  for (const row of ledger) {
    byTier[row.tier] = (byTier[row.tier] ?? 0) + 1;
    byStatus[row.status] = (byStatus[row.status] ?? 0) + 1;
  }

  const branch =
    spawnSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], { cwd: ctx.root, encoding: "utf8", windowsHide: true })
      .stdout?.trim() ?? "unknown";
  const dirty =
    spawnSync("git", ["status", "--porcelain"], { cwd: ctx.root, encoding: "utf8", windowsHide: true }).stdout?.trim()
      .length > 0;
  const upstream = spawnSync("git", ["rev-parse", "@{u}"], { cwd: ctx.root, encoding: "utf8", windowsHide: true });
  let headMatchesOrigin = null;
  if (upstream.status === 0) {
    const diff = spawnSync("git", ["rev-parse", "HEAD", "@{u}"], { cwd: ctx.root, encoding: "utf8", windowsHide: true });
    const parts = (diff.stdout ?? "").trim().split(/\s+/);
    headMatchesOrigin = parts.length === 2 && parts[0] === parts[1];
  }

  const required = requiredTools(ctx);
  const toolStatus = required.map((name) => ({
    name,
    present: checkToolPresent(ctx.root, name),
  }));

  return {
    project: projectName(ctx),
    displayName: displayName(ctx),
    capabilities: ctx.config.capabilities,
    branch,
    dirty,
    headMatchesOrigin,
    ledger: { total: ledger.length, byTier, byStatus },
    tools: { required: toolStatus, missing: toolStatus.filter((t) => !t.present).map((t) => t.name) },
  };
}

/**
 * @param {string} root
 * @param {string} name
 */
function checkToolPresent(root, name) {
  const registryPath = inside(root, ".hyperpower/tools/registry.json");
  if (fs.existsSync(registryPath)) {
    const reg = JSON.parse(fs.readFileSync(registryPath, "utf8"));
    const entry = reg.tools?.find((t) => t.name === name || t.name === `${name}-scanner`);
    if (entry?.installPath) {
      return fs.existsSync(inside(root, entry.installPath));
    }
  }
  switch (name) {
    case "playwright":
      return fs.existsSync(inside(root, "node_modules/@playwright/test"));
    case "impeccable":
      return fs.existsSync(inside(root, "node_modules/impeccable")) || fs.existsSync(inside(root, "node_modules/.bin/impeccable"));
    case "graphify":
      return (
        fs.existsSync(inside(root, "scripts/graphify-pre-push-hook.mjs")) ||
        fs.existsSync(inside(root, "node_modules/.bin/graphify"))
      );
    case "osv":
      return fs.existsSync(inside(root, ".hyperpower/tools/bin/osv-scanner.exe"));
    case "betterleaks":
      return fs.existsSync(inside(root, ".hyperpower/tools/bin/betterleaks.exe"));
    case "beads":
      return (
        fs.existsSync(inside(root, ".hyperpower/tools/bin/bd.exe")) ||
        fs.existsSync(inside(root, ".hyperpower/tools/bin/bd"))
      );
    default:
      return false;
  }
}

/**
 * @param {string} [startDir]
 */
export function printStatus(startDir = process.cwd()) {
  const report = buildStatusReport(startDir);
  console.log(JSON.stringify(report, null, 2));
  return report;
}
