#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { iso } from "./common.mjs";
import { readPhaseSync } from "./beads.mjs";
import { readLedger } from "./evidence.mjs";
import { defaultBranch, loadProject, projectName, phasesConfig } from "./project.mjs";

/**
 * @param {string} [startDir]
 */
export function buildHandoff(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const commitSha =
    spawnSync("git", ["rev-parse", "HEAD"], { cwd: ctx.root, encoding: "utf8", windowsHide: true }).stdout?.trim() ??
    "unknown";
  const branch =
    spawnSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], { cwd: ctx.root, encoding: "utf8", windowsHide: true })
      .stdout?.trim() ?? "unknown";

  const ledger = readLedger(startDir);
  const buckets = {
    VERIFIED: ledger.filter((r) => r.status === "VERIFIED").map((r) => r.id),
    DEFERRED: ledger.filter((r) => r.status === "DEFERRED").map((r) => r.id),
    BROKEN: ledger.filter((r) => r.status === "BROKEN").map((r) => r.id),
  };

  const phaseSync = readPhaseSync(startDir);
  const phases = phasesConfig(ctx);
  const currentPhase =
    Object.keys(phases).find((p) => phaseSync?.phases?.[p]?.syncStatus === "VERIFIED_SYNCHRONIZED") ??
    Object.keys(phases)[0] ??
    null;

  return {
    schemaVersion: 1,
    generatedUtc: iso(),
    project: projectName(ctx),
    repo: { remote: ctx.config.repo?.remote ?? null, branch, defaultBranch: defaultBranch(ctx) },
    commitSha,
    deployedSha: null,
    currentPhase,
    buckets,
    changes: [],
    tests: {},
    acceptanceImpact: "none",
    memoryChanges: [],
    cost: { spendAuthorized: false, note: "handoff is read-only aggregation" },
    humanActionRequired: [],
  };
}

/**
 * @param {string} [startDir]
 */
export function printHandoff(startDir = process.cwd()) {
  const doc = buildHandoff(startDir);
  console.log(JSON.stringify(doc, null, 2));
  return doc;
}
