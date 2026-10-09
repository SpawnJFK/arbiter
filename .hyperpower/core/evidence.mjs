#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { hash, inside, iso } from "./common.mjs";
import { loadProject } from "./project.mjs";

const TIERS = new Set(["self-hashed", "replayable", "attested"]);

/**
 * @param {Record<string, unknown>} input
 * @param {string} [startDir]
 */
export function appendRecord(input, startDir = process.cwd()) {
  const { root } = loadProject(startDir);
  const tier = String(input.tier ?? "");
  if (!TIERS.has(tier)) {
    throw new Error(`invalid tier: ${tier}`);
  }
  if (tier === "attested") {
    throw new Error(
      "attested tier is not supported yet: no CI signer produces attested records in this project."
    );
  }
  const verifier = input.verifier;
  if (tier === "replayable") {
    if (!verifier || typeof verifier !== "object" || !/** @type {Record<string, unknown>} */ (verifier).kind) {
      throw new Error("replayable tier requires a verifier with a kind; refusing to write an unverifiable replayable record.");
    }
  }

  const claim = String(input.claim ?? "");
  const artifactRel = String(input.artifact ?? "");
  if (!claim || !artifactRel) throw new Error("claim and artifact are required");

  const artifactPath = inside(root, artifactRel);
  if (!fs.existsSync(artifactPath)) {
    throw new Error(`artifact not found: ${artifactRel}`);
  }
  const artifactBytes = fs.readFileSync(artifactPath);
  const sha256 = hash(artifactBytes);
  const id = `EV-${hash(Buffer.concat([Buffer.from(claim, "utf8"), artifactBytes])).slice(0, 8)}`;

  const commit =
    input.commit ??
    spawnSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8", windowsHide: true }).stdout?.trim() ??
    "unknown";

  const record = {
    id,
    claim,
    tier,
    verifier: verifier ?? { kind: "manual", notes: "self-hashed summary" },
    artifact: artifactRel.replace(/\\/g, "/"),
    sha256,
    commit,
    observedUtc: input.observedUtc ?? iso(),
    status: input.status ?? "DEFERRED",
  };

  if (input.supersedes) {
    record.supersedes = String(input.supersedes);
  }

  const ledgerPath = inside(root, "evidence/ledger.jsonl");
  fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
  fs.appendFileSync(ledgerPath, `${JSON.stringify(record)}\n`, "utf8");
  return record;
}

/**
 * @param {string} [startDir]
 */
export function readLedger(startDir = process.cwd()) {
  const { root } = loadProject(startDir);
  const ledgerPath = inside(root, "evidence/ledger.jsonl");
  if (!fs.existsSync(ledgerPath)) return [];
  const lines = fs.readFileSync(ledgerPath, "utf8").split(/\r?\n/).filter(Boolean);
  return lines.map((line) => JSON.parse(line));
}
