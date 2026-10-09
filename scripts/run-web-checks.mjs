#!/usr/bin/env node
// npm run verify:web: the web half of the ship check, same steps as CI job "web":
// lint (ESLint, then i18n:check), typecheck (tsc --noEmit), production build.
// The e2e browser test is separate (npm run verify:e2e) because it needs a running API,
// worker and web server.

import fs from "node:fs";
import path from "node:path";
import { isWin, npmCommand, root, runSteps } from "./lib/proc.mjs";

const cwd = path.join(root, "apps", "web");
if (!fs.existsSync(path.join(cwd, "node_modules"))) {
  console.error("[verify:web] apps/web/node_modules is missing. Install with `npm ci` in apps/web.");
  process.exit(1);
}

const env = { ...process.env, NEXT_TELEMETRY_DISABLED: "1" };
const npm = npmCommand();
// On Windows npm is npm.cmd; Node refuses to spawn .cmd files without a shell. Arguments are fixed.
await runSteps("verify:web", [
  { cmd: npm, args: ["run", "lint"], cwd, env, shell: isWin },
  { cmd: npm, args: ["run", "typecheck"], cwd, env, shell: isWin },
  { cmd: npm, args: ["run", "build"], cwd, env, shell: isWin },
]);
