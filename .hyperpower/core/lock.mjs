#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { hash, inside, writeJSON, iso } from "./common.mjs";
import { loadProject } from "./project.mjs";

export const CORE_VERSION = "1.0.0";

/**
 * @param {string} [startDir]
 */
export function regenerateCoreLock(startDir = process.cwd()) {
  const { root } = loadProject(startDir);
  const coreDir = inside(root, ".hyperpower/core");
  /** @type {Record<string, string>} */
  const files = {};
  for (const name of fs.readdirSync(coreDir)) {
    if (name === "core.lock.json") continue;
    if (!name.endsWith(".mjs")) continue;
    const buf = fs.readFileSync(path.join(coreDir, name));
    files[name] = hash(buf);
  }
  const lock = {
    coreVersion: CORE_VERSION,
    generatedUtc: iso(),
    files,
  };
  writeJSON(path.join(coreDir, "core.lock.json"), lock);
  return lock;
}
