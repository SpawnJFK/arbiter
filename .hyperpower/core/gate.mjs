#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { inside, iso, run } from "./common.mjs";
import { BeadsReadBackError, closeWithReadBack, upsertPhaseState } from "./beads.mjs";
import { readLedger } from "./evidence.mjs";
import { loadProject, phaseEntry, requiredEvidenceTier, shipScript } from "./project.mjs";
import { verifyRecord } from "./verify.mjs";

export class GateError extends Error {
  /**
   * @param {string} message
   * @param {string} code
   */
  constructor(message, code) {
    super(message);
    this.name = "GateError";
    this.code = code;
  }
}

/**
 * @param {string} phaseId
 * @param {{ mode?: "bootstrap" | "product", startDir?: string }} [options]
 */
export async function runGate(phaseId, options = {}) {
  const startDir = options.startDir ?? process.cwd();
  const ctx = loadProject(startDir);
  const phase = phaseEntry(ctx, phaseId);
  const gateKind = /** @type {"phase"|"verticalSlice"|"launch"} */ (phase.gateKind ?? "phase");
  const requiredTier = requiredEvidenceTier(ctx, gateKind);
  const beadId = String(phase.beadId ?? "");
  const evidenceIds = /** @type {string[]} */ (phase.evidenceIds ?? []);

  const buckets = { VERIFIED: [], DEFERRED: [], BROKEN: [] };

  const report = {
    phaseId,
    mode: options.mode ?? "bootstrap",
    startedUtc: iso(),
    requiredEvidenceTier: requiredTier,
    beadId,
    evidenceIds,
    buckets,
    exitCode: 1,
  };

  try {
    const ledger = readLedger(startDir);
    const selected = ledger.filter((r) => evidenceIds.includes(r.id));
    if (selected.length !== evidenceIds.length) {
      throw new GateError("missing evidence records for phase", "GATE_EVIDENCE_MISSING");
    }

    for (const record of selected) {
      if (record.tier === "self-hashed") {
        throw new GateError(
          `required claim ${record.id} is self-hashed only; gate refuses self-hashed proof`,
          "GATE_SELF_HASHED_ONLY"
        );
      }
      if (record.tier !== requiredTier && record.tier !== "replayable" && requiredTier === "replayable") {
        throw new GateError(`record ${record.id} tier ${record.tier} below required ${requiredTier}`, "GATE_TIER_TOO_WEAK");
      }
    }

    for (const record of selected) {
      const { outcome, detail } = await verifyRecord(record, ctx);
      if (outcome === "STALE") {
        throw new GateError(`verifier STALE for ${record.id}: ${detail}`, "GATE_VERIFY_STALE");
      }
      if (outcome === "BROKEN") {
        throw new GateError(`verifier BROKEN for ${record.id}: ${detail}`, "GATE_VERIFY_BROKEN");
      }
      buckets.VERIFIED.push({ id: record.id, detail });
    }

    if ((options.mode ?? "bootstrap") === "product") {
      const script = shipScript(ctx);
      const npm = process.platform === "win32" ? "npm.cmd" : "npm";
      const ship = await run(npm, ["run", script.replace(/^npm run /, "")], {
        cwd: ctx.root,
        timeoutMs: 900_000,
      });
      if (ship.exitCode !== 0) {
        throw new GateError(`ship script ${script} failed`, "GATE_SHIP_FAILED");
      }
      buckets.VERIFIED.push({ id: "ship", detail: script });
    }

    let closeResult;
    try {
      closeResult = await closeWithReadBack(beadId, `gate pass ${phaseId} ${iso()}`, ctx.root);
    } catch (e) {
      const code =
        e instanceof BeadsReadBackError
          ? e.code
          : e instanceof Error && "code" in e
            ? String(e.code)
            : "BEADS_READBACK_UNVERIFIABLE";
      upsertPhaseState(
        phaseId,
        {
          beadId,
          localStatus: "VERIFIED_LOCAL",
          syncStatus: "VERIFIED_LOCAL",
          error: e instanceof Error ? e.message : String(e),
          errorCode: code,
          synchronizedUtc: null,
          closeResult: null,
        },
        ctx.root
      );
      throw new GateError(e instanceof Error ? e.message : String(e), code);
    }

    if (closeResult.alreadyClosed && !phase.allowAlreadyClosed) {
      upsertPhaseState(
        phaseId,
        {
          beadId,
          localStatus: "VERIFIED_LOCAL",
          syncStatus: "VERIFIED_LOCAL",
          error: "bead already closed before this gate run",
          errorCode: "GATE_BEAD_ALREADY_CLOSED",
          synchronizedUtc: null,
          closeResult: closeResult,
        },
        ctx.root
      );
      throw new GateError("bead already closed; read-back gate refused", "GATE_BEAD_ALREADY_CLOSED");
    }

    upsertPhaseState(
      phaseId,
      {
        beadId,
        localStatus: "PASS",
        syncStatus: "VERIFIED_SYNCHRONIZED",
        synchronizedUtc: closeResult.closedAt,
        closeResult: {
          closedAt: closeResult.closedAt,
          closeReason: closeResult.closeReason,
          alreadyClosed: closeResult.alreadyClosed,
        },
      },
      ctx.root
    );

    report.exitCode = 0;
    report.closeResult = closeResult;
  } catch (e) {
    const code = e instanceof GateError ? e.code : e instanceof Error && "code" in e ? String(e.code) : "GATE_FAILED";
    const message = e instanceof Error ? e.message : String(e);
    buckets.BROKEN.push({ id: phaseId, detail: message, rootCause: code });
    report.error = { code, message };
    if (!readPhaseSyncSafe(ctx.root, phaseId)) {
      const syncStatus =
        code === "GATE_SELF_HASHED_ONLY" || code === "GATE_VERIFY_STALE" || code === "GATE_VERIFY_BROKEN"
          ? "IN_PROGRESS"
          : "IN_PROGRESS";
      upsertPhaseState(
        phaseId,
        {
          beadId,
          localStatus: syncStatus === "IN_PROGRESS" ? "IN_PROGRESS" : "VERIFIED_LOCAL",
          syncStatus,
          error: message,
          errorCode: code,
        },
        ctx.root
      );
    }
    report.exitCode = 1;
  }

  report.finishedUtc = iso();
  const outDir = inside(ctx.root, "reports/gates");
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, `${phaseId}-${Date.now()}.json`);
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  report.reportPath = path.relative(ctx.root, outPath).replace(/\\/g, "/");
  return report;
}

function readPhaseSyncSafe(root, phaseId) {
  try {
    const p = inside(root, ".hyperpower/state/phase-sync.json");
    if (!fs.existsSync(p)) return false;
    const data = JSON.parse(fs.readFileSync(p, "utf8"));
    return Boolean(data.phases?.[phaseId]);
  } catch {
    return false;
  }
}

/**
 * @param {string} phaseId
 * @param {Record<string, unknown>} options
 */
export async function printGate(phaseId, options = {}) {
  const report = await runGate(phaseId, options);
  console.log(JSON.stringify(report, null, 2));
  return report;
}
