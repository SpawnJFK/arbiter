#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { inside, iso, run, writeJSON } from "./common.mjs";
import { beadsBinary, loadProject, phaseEntry, phasesConfig } from "./project.mjs";

export class BeadsReadBackError extends Error {
  /**
   * @param {string} message
   * @param {"BEADS_NOT_CLOSED"|"BEADS_READBACK_UNVERIFIABLE"|"BEADS_READBACK_FAILED"} code
   */
  constructor(message, code = "BEADS_READBACK_UNVERIFIABLE") {
    super(message);
    this.name = "BeadsReadBackError";
    this.code = code;
  }
}

/**
 * Parse the first complete JSON value from bd CLI output (stdout may include log noise).
 * @param {string} raw
 */
export function parseBdJson(raw) {
  const text = raw.replace(/^\uFEFF/, "").replace(/\u0000/g, "");
  let start = -1;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "{" || c === "[") {
      start = i;
      break;
    }
  }
  if (start < 0) {
    throw new BeadsReadBackError("beads CLI did not return JSON", "BEADS_READBACK_UNVERIFIABLE");
  }
  const open = text[start];
  const close = open === "{" ? "}" : "]";
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = start; i < text.length; i++) {
    const c = text[i];
    if (inString) {
      if (escape) escape = false;
      else if (c === "\\") escape = true;
      else if (c === '"') inString = false;
      continue;
    }
    if (c === '"') {
      inString = true;
      continue;
    }
    if (c === open) depth++;
    else if (c === close) {
      depth--;
      if (depth === 0) {
        const slice = text.slice(start, i + 1);
        try {
          return JSON.parse(slice);
        } catch (e) {
          throw new BeadsReadBackError(
            e instanceof Error ? e.message : String(e),
            "BEADS_READBACK_UNVERIFIABLE"
          );
        }
      }
    }
  }
  throw new BeadsReadBackError("incomplete JSON in beads CLI output", "BEADS_READBACK_UNVERIFIABLE");
}

/** @deprecated use parseBdJson */
function parseJsonOut(raw) {
  return parseBdJson(raw);
}

/**
 * @param {string} root
 * @param {string[]} args
 */
async function runBd(root, args) {
  const bin = beadsBinary(loadProject(root));
  const result = await run(bin, args, { cwd: root, timeoutMs: 120_000 });
  if (result.exitCode !== 0) {
    throw new Error(`beads CLI failed (${result.exitCode}): ${result.output.slice(0, 500)}`);
  }
  return result.output.trim();
}

/**
 * @param {string} [startDir]
 */
export async function healthCheck(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const bin = beadsBinary(ctx);
  const versionOut = await run(bin, ["version"], { cwd: ctx.root, timeoutMs: 30_000 });
  const listOut = await run(bin, ["list", "--json"], { cwd: ctx.root, timeoutMs: 60_000 });
  const list = parseBdJson(listOut.output);
  const phases = phasesConfig(ctx);
  const mapping = [];
  for (const [phaseId, entry] of Object.entries(phases)) {
    const beadId = String(/** @type {Record<string, unknown>} */ (entry).beadId ?? "");
    if (!beadId) {
      mapping.push({ phaseId, beadId, ok: false, error: "missing beadId in hyperpower.json" });
      continue;
    }
    try {
      await fetchBead(beadId, ctx.root);
      mapping.push({ phaseId, beadId, ok: true });
    } catch (e) {
      mapping.push({
        phaseId,
        beadId,
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }
  return {
    ok: mapping.every((m) => m.ok) && versionOut.exitCode === 0,
    version: versionOut.output.trim(),
    listCount: Array.isArray(list) ? list.length : 0,
    phaseMappings: mapping,
  };
}

/**
 * @param {string} beadId
 * @param {string} [startDir]
 */
export async function fetchBead(beadId, startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const bin = beadsBinary(ctx);
  const out = await run(bin, ["show", beadId, "--json"], { cwd: ctx.root, timeoutMs: 60_000 });
  let parsed;
  try {
    parsed = parseBdJson(out.output);
  } catch (e) {
    if (e instanceof BeadsReadBackError) throw e;
    throw new BeadsReadBackError(
      e instanceof Error ? e.message : String(e),
      "BEADS_READBACK_UNVERIFIABLE"
    );
  }
  const bead = Array.isArray(parsed) ? parsed[0] : parsed;
  if (!bead?.id) {
    throw new BeadsReadBackError(`bead not found: ${beadId}`, "BEADS_READBACK_UNVERIFIABLE");
  }
  return bead;
}

/**
 * @param {Array<{ title: string, priority?: number, id?: string }>} items
 * @param {Array<{ from: string, to: string, type?: string }>} edges
 * @param {string} [startDir]
 */
export async function createAndLink(items, edges, startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const bin = beadsBinary(ctx);
  /** @type {Record<string, string>} */
  const ids = {};
  for (const item of items) {
    const args = ["create", item.title, "-p", String(item.priority ?? 2), "--json"];
    const out = await run(bin, args, { cwd: ctx.root, timeoutMs: 60_000 });
    const created = parseBdJson(out.output);
    const id = created.id ?? created[0]?.id;
    if (!id) throw new Error("create did not return id");
    ids[item.title] = id;
  }
  for (const edge of edges) {
    const child = ids[edge.from] ?? edge.from;
    const parent = ids[edge.to] ?? edge.to;
    const depType = edge.type ?? "blocks";
    await run(bin, ["dep", "add", child, parent, depType], { cwd: ctx.root, timeoutMs: 60_000 });
  }
  return ids;
}

/**
 * @param {string} beadId
 * @param {string} reason
 * @param {string} [startDir]
 */
export async function closeWithReadBack(beadId, reason, startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  let before;
  try {
    before = await fetchBead(beadId, ctx.root);
  } catch (e) {
    if (e instanceof BeadsReadBackError && e.code === "BEADS_READBACK_UNVERIFIABLE") throw e;
    throw new BeadsReadBackError(
      e instanceof Error ? e.message : String(e),
      "BEADS_READBACK_UNVERIFIABLE"
    );
  }
  if (before.status === "closed") {
    return {
      outcome: "VERIFIED_SYNCHRONIZED",
      alreadyClosed: true,
      beadId,
      closedAt: before.closed_at ?? before.updated_at,
      closeReason: before.close_reason ?? null,
      bead: before,
    };
  }

  const bin = beadsBinary(ctx);
  const closeOut = await run(bin, ["close", beadId, "--reason", reason, "--json"], {
    cwd: ctx.root,
    timeoutMs: 60_000,
  });
  if (closeOut.exitCode !== 0) {
    throw new BeadsReadBackError(
      `beads close failed (${closeOut.exitCode})`,
      "BEADS_READBACK_UNVERIFIABLE"
    );
  }

  let after;
  try {
    after = await fetchBead(beadId, ctx.root);
  } catch (e) {
    throw new BeadsReadBackError(
      `close command ran but read-back could not parse bead: ${e instanceof Error ? e.message : String(e)}`,
      "BEADS_READBACK_UNVERIFIABLE"
    );
  }
  if (after.status !== "closed") {
    throw new BeadsReadBackError(
      `read-back after close did not show closed status for ${beadId}`,
      "BEADS_NOT_CLOSED"
    );
  }
  if (!after.closed_at) {
    throw new BeadsReadBackError(
      `read-back missing server closed_at for ${beadId}`,
      "BEADS_NOT_CLOSED"
    );
  }

  return {
    outcome: "VERIFIED_SYNCHRONIZED",
    alreadyClosed: false,
    beadId,
    closedAt: after.closed_at,
    closeReason: after.close_reason ?? reason,
    bead: after,
  };
}

/**
 * @param {Record<string, unknown>} phaseSync
 * @param {string} [startDir]
 */
export function writePhaseSync(phaseSync, startDir = process.cwd()) {
  const { root } = loadProject(startDir);
  const filePath = inside(root, ".hyperpower/state/phase-sync.json");
  writeJSON(filePath, { ...phaseSync, updatedUtc: iso() });
  return filePath;
}

/**
 * @param {string} [startDir]
 */
export function readPhaseSync(startDir = process.cwd()) {
  const { root } = loadProject(startDir);
  const filePath = inside(root, ".hyperpower/state/phase-sync.json");
  if (!fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

/**
 * @param {string} phaseId
 * @param {Record<string, unknown>} phaseState
 * @param {string} [startDir]
 */
export function upsertPhaseState(phaseId, phaseState, startDir = process.cwd()) {
  const existing = readPhaseSync(startDir) ?? { phases: {} };
  const phases = existing.phases ?? {};
  phases[phaseId] = phaseState;
  writePhaseSync({ ...existing, phases }, startDir);
  return phases[phaseId];
}
