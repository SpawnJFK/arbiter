#!/usr/bin/env node
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { inside, iso } from "./common.mjs";
import { fetchBead, readPhaseSync } from "./beads.mjs";
import { loadProject, phasesConfig } from "./project.mjs";

/**
 * @param {string} [startDir]
 */
export async function runResume(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  /** @type {Array<{ kind: string, detail: string }>} */
  const disagreements = [];

  const head =
    spawnSync("git", ["rev-parse", "HEAD"], { cwd: ctx.root, encoding: "utf8", windowsHide: true }).stdout?.trim() ??
    "";
  const sessionPath = inside(ctx.root, ".hyperpower/state/session.json");
  if (fs.existsSync(sessionPath)) {
    const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
    if (session.commitSha && session.commitSha !== head) {
      disagreements.push({
        kind: "git",
        detail: `session commit ${session.commitSha} != HEAD ${head}`,
      });
    }
  }

  const phaseSync = readPhaseSync(startDir);
  const phases = phasesConfig(ctx);
  for (const [phaseId, entry] of Object.entries(phases)) {
    const beadId = String(/** @type {Record<string, unknown>} */ (entry).beadId ?? "");
    const stored = phaseSync?.phases?.[phaseId];
    if (!stored || !beadId) continue;
    try {
      const bead = await fetchBead(beadId, ctx.root);
      if (stored.syncStatus === "VERIFIED_SYNCHRONIZED" && bead.status !== "closed") {
        disagreements.push({
          kind: "beads",
          detail: `phase ${phaseId} marked VERIFIED_SYNCHRONIZED but bead ${beadId} status is ${bead.status}`,
        });
      }
      if (stored.closeResult?.closedAt && bead.closed_at && stored.closeResult.closedAt !== bead.closed_at) {
        disagreements.push({
          kind: "beads",
          detail: `phase ${phaseId} close timestamp mismatch for ${beadId}`,
        });
      }
    } catch (e) {
      disagreements.push({
        kind: "beads",
        detail: `bead ${beadId} for phase ${phaseId} not reachable: ${e instanceof Error ? e.message : String(e)}`,
      });
    }
  }

  return {
    checkedUtc: iso(),
    disagreements,
    ok: disagreements.length === 0,
  };
}

/**
 * @param {string} [startDir]
 */
export async function printResume(startDir = process.cwd()) {
  const report = await runResume(startDir);
  console.log(JSON.stringify(report, null, 2));
  return report;
}
