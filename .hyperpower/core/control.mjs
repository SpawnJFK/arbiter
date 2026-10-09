#!/usr/bin/env node
import { appendRecord } from "./evidence.mjs";
import { printDoctor } from "./doctor.mjs";
import { regenerateCoreLock } from "./lock.mjs";
import { printStatus } from "./status.mjs";
import { verifyAll } from "./verify.mjs";
import { healthCheck } from "./beads.mjs";
import { printGate } from "./gate.mjs";
import { printHandoff } from "./handoff.mjs";
import { printResume } from "./resume.mjs";
import { printEnd } from "./end.mjs";

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || cmd === "help" || cmd === "--help") {
    console.log(`Usage: npm run hp -- <command>

Commands:
  doctor              integrity and policy checks
  status              read-only project state
  verify [recordId]   replay ledger verifiers
  evidence append     append ledger record from JSON file path
  lock                regenerate core.lock.json
  beads health        beads CLI + phase mapping health
  gate <phaseId>      run phase gate (--bootstrap | --product)
  handoff             planner handoff document (JSON)
  resume              reconcile session/beads/git state
  end                 persist session checkpoint
`);
    process.exit(0);
  }

  try {
    switch (cmd) {
      case "doctor": {
        const result = printDoctor();
        process.exit(result.exitCode);
      }
      case "status": {
        printStatus();
        process.exit(0);
      }
      case "verify": {
        const summary = await verifyAll(rest[0]);
        console.log(JSON.stringify(summary, null, 2));
        process.exit(summary.broken > 0 ? 1 : 0);
      }
      case "lock": {
        const lock = regenerateCoreLock();
        console.log(JSON.stringify(lock, null, 2));
        process.exit(0);
      }
      case "evidence": {
        if (rest[0] !== "append" || !rest[1]) {
          console.error("Usage: npm run hp -- evidence append <record.json>");
          process.exit(1);
        }
        const fs = await import("node:fs");
        const input = JSON.parse(fs.readFileSync(rest[1], "utf8"));
        const record = appendRecord(input);
        console.log(JSON.stringify(record, null, 2));
        process.exit(0);
      }
      case "beads": {
        if (rest[0] === "health") {
          const h = await healthCheck();
          console.log(JSON.stringify(h, null, 2));
          process.exit(h.ok ? 0 : 1);
        }
        console.error("Usage: npm run hp -- beads health");
        process.exit(1);
      }
      case "gate": {
        const phaseId = rest[0];
        if (!phaseId) {
          console.error("Usage: npm run hp -- gate <phaseId> [--bootstrap|--product]");
          process.exit(1);
        }
        const mode = rest.includes("--product") ? "product" : "bootstrap";
        const report = await printGate(phaseId, { mode });
        process.exit(report.exitCode);
      }
      case "handoff": {
        printHandoff();
        process.exit(0);
      }
      case "resume": {
        const report = await printResume();
        process.exit(report.ok ? 0 : 1);
      }
      case "end": {
        printEnd();
        process.exit(0);
      }
      default:
        console.error(`Unknown command: ${cmd}`);
        process.exit(1);
    }
  } catch (e) {
    console.error(e instanceof Error ? e.message : String(e));
    process.exit(1);
  }
}

main();
