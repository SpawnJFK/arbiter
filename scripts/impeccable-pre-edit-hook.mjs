#!/usr/bin/env node
// Cursor preToolUse hook: runs Impeccable `hook-before-edit` through the skill's launcher.
// NOT wired in .cursor/hooks.json yet: the Impeccable engine binary is not in the repo (the
// launcher downloads the version in .cursor/skills/impeccable/scripts/VERSION, verified against
// its .sha256 sidecar, into IMPECCABLE_HOME). P00 installs it, adds this hook to hooks.json and
// proves it through a real Cursor edit.
//
// Fails open (exit 0) when the engine is missing: this hook advises on design, it guards nothing.

import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const scripts = path.join(root, ".cursor", "skills", "impeccable", "scripts");

if (process.platform === "win32") {
  const cmd = path.join(scripts, "impeccable.cmd");
  if (existsSync(cmd)) {
    // .cmd needs cmd.exe; the argument is fixed.
    spawnSync(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", `"${cmd}" hook-before-edit`], {
      cwd: root,
      stdio: "inherit",
      windowsHide: true,
      windowsVerbatimArguments: true,
    });
  }
} else {
  const sh = path.join(scripts, "impeccable");
  if (existsSync(sh)) spawnSync("sh", [sh, "hook-before-edit"], { cwd: root, stdio: "inherit" });
}
process.exit(0);
