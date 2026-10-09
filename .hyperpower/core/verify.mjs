#!/usr/bin/env node
import fs from "node:fs";
import https from "node:https";
import http from "node:http";
import { spawnSync } from "node:child_process";
import { inside, parseCliCommand, run } from "./common.mjs";
import { loadProject } from "./project.mjs";
import { readLedger } from "./evidence.mjs";

/** @typedef {"VERIFIED"|"STALE"|"BROKEN"} VerifyOutcome */

/**
 * @param {Record<string, unknown>} record
 * @param {{ root: string }} ctx
 * @returns {Promise<{ outcome: VerifyOutcome, detail: string }>}
 */
export async function verifyRecord(record, ctx) {
  const tier = record.tier;
  if (tier !== "replayable") {
    return { outcome: "STALE", detail: `tier ${tier} is not replayable` };
  }
  const verifier = record.verifier;
  if (!verifier || typeof verifier !== "object") {
    return { outcome: "STALE", detail: "missing verifier" };
  }
  const kind = /** @type {Record<string, unknown>} */ (verifier).kind;
  try {
    switch (kind) {
      case "cli":
        return await verifyCli(/** @type {Record<string, unknown>} */ (verifier), ctx);
      case "http":
        return await verifyHttp(/** @type {Record<string, unknown>} */ (verifier));
      case "commit-exists":
        return verifyCommitExists(/** @type {Record<string, unknown>} */ (verifier), ctx);
      case "playwright":
        return verifyPlaywright(/** @type {Record<string, unknown>} */ (verifier), ctx);
      case "sql":
        return verifySql(/** @type {Record<string, unknown>} */ (verifier), ctx);
      default:
        return { outcome: "STALE", detail: `unsupported verifier kind: ${kind}` };
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (/ENOENT|not found|missing|unreachable|ECONNREFUSED|ENOTFOUND/i.test(msg)) {
      return { outcome: "STALE", detail: msg };
    }
    return { outcome: "BROKEN", detail: msg };
  }
}

/**
 * @param {Record<string, unknown>} verifier
 * @param {{ root: string }} ctx
 */
async function verifyCli(verifier, ctx) {
  const cmd = String(verifier.command ?? "");
  if (!cmd) return { outcome: "STALE", detail: "cli verifier missing command" };
  let parsed;
  try {
    parsed = parseCliCommand(cmd, ctx.root);
  } catch (e) {
    return { outcome: "STALE", detail: e instanceof Error ? e.message : String(e) };
  }
  if (!fs.existsSync(parsed.command) && parsed.command !== process.execPath && parsed.command !== "git" && parsed.command !== "gh") {
    return { outcome: "STALE", detail: `executable not found: ${parsed.command}` };
  }
  const expectCode = verifier.expectExitCode ?? 0;
  const result = await run(parsed.command, parsed.args, { cwd: ctx.root, timeoutMs: verifier.timeoutMs ?? 600_000 });
  if (result.exitCode !== expectCode) {
    return { outcome: "BROKEN", detail: `exit ${result.exitCode}, expected ${expectCode}` };
  }
  if (verifier.expectOutputContains) {
    const needle = String(verifier.expectOutputContains);
    if (!result.output.includes(needle)) {
      return { outcome: "BROKEN", detail: `output missing expected substring` };
    }
  }
  return { outcome: "VERIFIED", detail: "cli verifier passed" };
}

/**
 * @param {Record<string, unknown>} verifier
 */
async function verifyHttp(verifier) {
  const url = String(verifier.url ?? "");
  if (!url) return { outcome: "STALE", detail: "http verifier missing url" };
  const expectStatus = Number(verifier.expectStatus ?? 200);
  const body = await fetchUrl(url);
  if (body.status !== expectStatus) {
    return { outcome: "BROKEN", detail: `status ${body.status}, expected ${expectStatus}` };
  }
  if (verifier.expectBodyContains) {
    if (!body.text.includes(String(verifier.expectBodyContains))) {
      return { outcome: "BROKEN", detail: "body missing expected substring" };
    }
  }
  return { outcome: "VERIFIED", detail: "http verifier passed" };
}

function fetchUrl(url) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith("https:") ? https : http;
    const req = lib.get(url, (res) => {
      let text = "";
      res.on("data", (c) => {
        text += c;
      });
      res.on("end", () => resolve({ status: res.statusCode ?? 0, text }));
    });
    req.on("error", (e) => reject(e));
    req.setTimeout(30_000, () => {
      req.destroy(new Error("http timeout"));
    });
  });
}

/**
 * @param {Record<string, unknown>} verifier
 * @param {{ root: string }} ctx
 */
function verifyCommitExists(verifier, ctx) {
  const sha = String(verifier.sha ?? verifier.commit ?? "");
  if (!sha) return { outcome: "STALE", detail: "commit-exists missing sha" };
  const r = spawnSync("git", ["cat-file", "-e", `${sha}^{commit}`], { cwd: ctx.root, windowsHide: true });
  if (r.status !== 0) return { outcome: "BROKEN", detail: "commit not reachable" };
  return { outcome: "VERIFIED", detail: "commit exists" };
}

/**
 * @param {Record<string, unknown>} verifier
 * @param {{ root: string }} ctx
 */
function verifyPlaywright(verifier, ctx) {
  const spec = String(verifier.spec ?? verifier.path ?? "");
  if (!spec) return { outcome: "STALE", detail: "playwright verifier missing spec" };
  const abs = inside(ctx.root, spec);
  if (!fs.existsSync(abs)) return { outcome: "STALE", detail: `spec not found: ${spec}` };
  const r = spawnSync("npx", ["playwright", "test", abs], {
    cwd: ctx.root,
    encoding: "utf8",
    windowsHide: true,
    shell: false,
  });
  if (r.status !== 0) return { outcome: "BROKEN", detail: "playwright spec failed" };
  return { outcome: "VERIFIED", detail: "playwright spec passed" };
}

/**
 * @param {Record<string, unknown>} verifier
 * @param {{ root: string }} ctx
 */
function verifySql(verifier, ctx) {
  const query = String(verifier.query ?? "");
  if (!query) return { outcome: "STALE", detail: "sql verifier missing query" };
  if (verifier.expect === undefined || verifier.expect === null) {
    return { outcome: "STALE", detail: "sql verifier missing expect" };
  }
  const script = inside(ctx.root, "scripts/run-sql-verifier.mjs");
  if (!fs.existsSync(script)) {
    return { outcome: "STALE", detail: "sql runner script not configured" };
  }
  const payload = JSON.stringify({
    query,
    expect: verifier.expect,
    params: verifier.params ?? {},
  });
  const r = spawnSync(process.execPath, [script], {
    cwd: ctx.root,
    encoding: "utf8",
    windowsHide: true,
    input: payload,
  });
  const detail = (r.stderr || r.stdout || "").trim() || "sql verifier finished";
  if (r.status === 2) return { outcome: "STALE", detail };
  if (r.status !== 0) return { outcome: "BROKEN", detail };
  return { outcome: "VERIFIED", detail: "sql verifier passed" };
}

/**
 * @param {string} [recordId]
 * @param {string} [startDir]
 */
export async function verifyAll(recordId, startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  const ledger = readLedger(startDir);
  const replayable = ledger.filter((r) => r.tier === "replayable" && (!recordId || r.id === recordId));
  if (recordId && replayable.length === 0) {
    throw new Error(`no replayable record with id ${recordId}`);
  }

  const results = [];
  for (const record of replayable) {
    const { outcome, detail } = await verifyRecord(record, ctx);
    results.push({ id: record.id, claim: record.claim, outcome, detail });
  }

  const summary = {
    total: results.length,
    verified: results.filter((r) => r.outcome === "VERIFIED").length,
    stale: results.filter((r) => r.outcome === "STALE").length,
    broken: results.filter((r) => r.outcome === "BROKEN").length,
    results,
  };
  return summary;
}
