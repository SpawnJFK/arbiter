#!/usr/bin/env node
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { inside, iso, writeJSON } from "./common.mjs";
import { buildHandoff } from "./handoff.mjs";
import { loadProject } from "./project.mjs";

/**
 * @param {string} [startDir]
 */
export function runEnd(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const handoff = buildHandoff(startDir);
  const dirty =
    spawnSync("git", ["status", "--porcelain"], { cwd: ctx.root, encoding: "utf8", windowsHide: true }).stdout?.trim()
      .length > 0;

  const session = {
    schemaVersion: 1,
    endedUtc: iso(),
    commitSha: handoff.commitSha,
    branch: handoff.repo.branch,
    dirty,
    currentPhase: handoff.currentPhase,
    handoff,
  };

  const sessionPath = inside(ctx.root, ".hyperpower/state/session.json");
  writeJSON(sessionPath, session);

  const checkpointDir = inside(ctx.root, ".hyperpower/state/checkpoints");
  fs.mkdirSync(checkpointDir, { recursive: true });
  const checkpointPath = `${checkpointDir}/end-${Date.now()}.json`;
  writeJSON(checkpointPath, session);

  return { sessionPath: sessionPath.replace(/\\/g, "/"), checkpointPath, session };
}

/**
 * @param {string} [startDir]
 */
export function printEnd(startDir = process.cwd()) {
  const result = runEnd(startDir);
  console.log(JSON.stringify(result, null, 2));
  return result;
}
