// Small process helpers shared by the root scripts (not part of the hash-locked core).
// Long steps print one newline-terminated status line every 30 seconds so progress is
// visible in a read-only agent terminal (CLAUDE.md law 9). Output streams through.

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
export const isWin = process.platform === "win32";

/** Python inside services/api/.venv (Windows: Scripts\python.exe), or null when the venv is missing. */
export function apiPython() {
  const rel = isWin ? ["services", "api", ".venv", "Scripts", "python.exe"] : ["services", "api", ".venv", "bin", "python"];
  const p = path.join(root, ...rel);
  return fs.existsSync(p) ? p : null;
}

/** npm executable name for spawn (on Windows npm is a .cmd and needs a shell). */
export function npmCommand() {
  return isWin ? "npm.cmd" : "npm";
}

function fmt(ms) {
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

/**
 * Run one step with inherited stdio and a 30 s heartbeat.
 * @param {{ label: string, n: number, total: number, cmd: string, args: string[], cwd: string, env?: NodeJS.ProcessEnv, shell?: boolean }} step
 * @returns {Promise<{ code: number, ms: number }>}
 */
export function runStep({ label, n, total, cmd, args, cwd, env, shell }) {
  const tag = `[${label}] step ${n}/${total}`;
  const pct = Math.round(((n - 1) / total) * 100);
  console.log(`${tag} start: ${[path.basename(cmd), ...args].join(" ")} (${pct}% of steps done)`);
  const t0 = Date.now();
  return new Promise((resolve) => {
    const child = spawn(cmd, args, {
      cwd,
      env: env ?? process.env,
      stdio: "inherit",
      shell: shell ?? false,
      windowsHide: true,
    });
    const beat = setInterval(() => {
      console.log(`${tag} still running, ${fmt(Date.now() - t0)} elapsed`);
    }, 30_000);
    const done = (code) => {
      clearInterval(beat);
      const ms = Date.now() - t0;
      console.log(`${tag} ${code === 0 ? "ok" : `FAILED (exit ${code})`} in ${fmt(ms)}`);
      resolve({ code, ms });
    };
    child.on("error", (err) => {
      console.error(`${tag} could not start: ${err.message}`);
      done(127);
    });
    child.on("close", (code, signal) => done(code ?? (signal ? 1 : 0)));
  });
}

/**
 * Run steps in order, stop at the first failure, exit with its code.
 * @param {string} label
 * @param {Array<Omit<Parameters<typeof runStep>[0], "label" | "n" | "total">>} steps
 */
export async function runSteps(label, steps) {
  const t0 = Date.now();
  for (let i = 0; i < steps.length; i++) {
    const { code } = await runStep({ label, n: i + 1, total: steps.length, ...steps[i] });
    if (code !== 0) {
      console.log(`[${label}] FAILED at step ${i + 1}/${steps.length} after ${fmt(Date.now() - t0)}`);
      process.exit(code);
    }
  }
  console.log(`[${label}] all ${steps.length} steps ok in ${fmt(Date.now() - t0)}`);
}
