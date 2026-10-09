#!/usr/bin/env node
// Cursor beforeShellExecution hook. Reads Cursor's JSON payload on stdin,
// asks the core guard (.hyperpower/core/guard.mjs) whether the command is
// allowed, and answers in Cursor's shape. The core stays hash-locked and
// version independent; if Cursor changes its hook contract, only this file
// changes. Proven only when P00 shows a denial inside Cursor itself.
//
// Fails closed on a payload it cannot read: a guard that silently allows on
// error is the failure mode this project has hit before.

import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function answer(allow, userMessage, agentMessage) {
  const body = {
    permission: allow ? "allow" : "deny",
    allow,
    userMessage: userMessage ?? undefined,
    agentMessage: agentMessage ?? undefined,
  };
  process.stdout.write(`${JSON.stringify(body)}\n`);
}

async function main() {
  let command;
  try {
    const payload = JSON.parse(await readStdin());
    command = typeof payload?.command === "string" ? payload.command : payload?.tool_input?.command;
  } catch {
    answer(false, "Shell guard could not read the hook payload.", "Hook payload was not valid JSON; command blocked.");
    return;
  }
  if (typeof command !== "string") {
    answer(false, "Shell guard got no command.", "Hook payload had no string command field; command blocked.");
    return;
  }

  const guard = await import(pathToFileURL(path.join(root, ".hyperpower/core/guard.mjs")).href);
  const decision = guard.evaluateCommand(command, { root });
  answer(decision.allow, decision.userMessage, decision.agentMessage);
}

main().then(
  () => process.exit(0),
  (err) => {
    answer(false, "Shell guard crashed.", `Guard error: ${err instanceof Error ? err.message : String(err)}`);
    process.exit(0);
  },
);
