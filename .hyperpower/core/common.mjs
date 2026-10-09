#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

const DANGEROUS_ARG = /[\r\n%"!&|<>^]/;

/** @returns {string} */
export function iso() {
  return new Date().toISOString();
}

/** @param {Buffer|string} input */
export function hash(input) {
  const buf = typeof input === "string" ? Buffer.from(input, "utf8") : input;
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/**
 * @param {string} text
 * @returns {string}
 */
export function redact(text) {
  if (text == null) return "";
  let s = String(text);
  s = s.replace(/\bghp_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_PAT]");
  s = s.replace(/\bgithub_pat_[A-Za-z0-9_]{20,}\b/g, "[REDACTED_GITHUB_PAT]");
  s = s.replace(/\bgho_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_OAUTH]");
  s = s.replace(/\bghu_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_USER]");
  s = s.replace(/\bghs_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_SERVER]");
  s = s.replace(/\bghr_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_REFRESH]");
  s = s.replace(/\bsk-[A-Za-z0-9_-]{10,}\b/g, "[REDACTED_SK]");
  s = s.replace(/\bsk-proj-[A-Za-z0-9_-]{10,}\b/g, "[REDACTED_SK]");
  s = s.replace(/\bsk-ant-[A-Za-z0-9_-]{10,}\b/g, "[REDACTED_SK]");
  s = s.replace(/\bctx7sk-[A-Za-z0-9-]+\b/g, "[REDACTED_CTX7]");
  s = s.replace(/\bBearer\s+[A-Za-z0-9._-]+\b/gi, "Bearer [REDACTED]");
  s = s.replace(
    /\b([A-Za-z0-9_]*(?:api_key|apikey|token|password|secret)[A-Za-z0-9_]*)\s*=\s*[^\s&'"]+/gi,
    "$1=[REDACTED]"
  );
  return s;
}

/**
 * @param {string} root
 * @param {string} target
 * @returns {string} resolved path inside root
 */
export function inside(root, target) {
  const rootResolved = path.resolve(root);
  const resolved = path.resolve(rootResolved, target);
  const rel = path.relative(rootResolved, resolved);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`path escapes project root: ${target}`);
  }
  let cur = resolved;
  while (cur !== rootResolved) {
    let st;
    try {
      st = fs.lstatSync(cur);
    } catch {
      break;
    }
    if (st.isSymbolicLink()) {
      throw new Error(`symbolic link in path: ${cur}`);
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return resolved;
}

/**
 * @param {string} filePath
 */
export function readJSON(filePath) {
  const raw = fs.readFileSync(filePath, "utf8");
  return JSON.parse(raw);
}

/**
 * @param {string} filePath
 * @param {unknown} data
 */
export function writeJSON(filePath, data) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`);
  fs.writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  fs.renameSync(tmp, filePath);
}

/**
 * @param {string} element
 * @returns {string}
 */
function quoteCmdElement(element) {
  if (DANGEROUS_ARG.test(element)) {
    throw new Error(`unsafe argument character in: ${redact(element)}`);
  }
  if (!/[\s"]/.test(element)) return element;
  return `"${element.replace(/"/g, '""')}"`;
}

/**
 * @param {string} command
 * @param {string[]} args
 * @param {{ cwd?: string, env?: NodeJS.ProcessEnv, timeoutMs?: number, capture?: boolean, onHeartbeat?: () => void }} [options]
 */
export function run(command, args, options = {}) {
  const { cwd = process.cwd(), env = process.env, timeoutMs, capture = true, onHeartbeat } = options;
  for (const a of args) {
    if (DANGEROUS_ARG.test(a)) {
      throw new Error(`unsafe argument character in: ${redact(a)}`);
    }
  }

  const started = iso();
  const t0 = Date.now();
  let execPath = command;
  let execArgs = args;

  if (process.platform === "win32") {
    const lower = command.toLowerCase();
    if (lower.endsWith(".cmd") || lower.endsWith(".bat")) {
      const line = [quoteCmdElement(command), ...args.map(quoteCmdElement)].join(" ");
      execPath = process.env.ComSpec || "cmd.exe";
      execArgs = ["/d", "/s", "/c", line];
    }
  }

  return new Promise((resolve, reject) => {
    const child = spawn(execPath, execArgs, {
      cwd,
      env,
      shell: false,
      windowsHide: true,
      stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
    });

    let stdout = "";
    let stderr = "";
    if (capture) {
      child.stdout?.on("data", (c) => {
        stdout += c.toString();
      });
      child.stderr?.on("data", (c) => {
        stderr += c.toString();
      });
    }

    const heartbeat = setInterval(() => {
      const msg = `[hp] still running: ${path.basename(execPath)} (${Math.round((Date.now() - t0) / 1000)}s)`;
      console.error(msg);
      onHeartbeat?.();
    }, 30_000);

    let timer;
    if (timeoutMs != null && timeoutMs > 0) {
      timer = setTimeout(() => {
        child.kill("SIGTERM");
        setTimeout(() => child.kill("SIGKILL"), 2000);
      }, timeoutMs);
    }

    child.on("error", (err) => {
      clearInterval(heartbeat);
      if (timer) clearTimeout(timer);
      reject(err);
    });

    child.on("close", (code, signal) => {
      clearInterval(heartbeat);
      if (timer) clearTimeout(timer);
      const combined = stdout + (stderr ? `\n${stderr}` : "");
      resolve({
        command: execPath,
        args: execArgs.map(String),
        exitCode: code ?? (signal ? 1 : 0),
        signal,
        output: redact(combined),
        started,
        durationMs: Date.now() - t0,
      });
    });
  });
}

/**
 * Find repository root containing hyperpower.json walking up from start.
 * @param {string} [start]
 */
export function findRepoRoot(start = process.cwd()) {
  let dir = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(dir, "hyperpower.json"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) throw new Error("hyperpower.json not found in any parent directory");
    dir = parent;
  }
}

/**
 * Split a simple CLI verifier command into executable + args (no shell).
 * @param {string} cmd
 * @param {string} repoRoot
 */
export function parseCliCommand(cmd, repoRoot) {
  const trimmed = cmd.trim();
  if (!trimmed) throw new Error("empty cli command");
  const parts = trimmed.match(/(?:[^\s"]+|"[^"]*")+/g);
  if (!parts?.length) throw new Error("unparseable cli command");
  const unquote = (p) => p.replace(/^"|"$/g, "").replace(/""/g, '"');
  const tokens = parts.map(unquote);
  let exe = tokens[0];
  let args = tokens.slice(1);
  if (exe === "node") {
    exe = process.execPath;
    args = tokens.slice(1).map((p) => (path.isAbsolute(p) ? p : path.join(repoRoot, p)));
  } else if (exe === "npx" || exe === "git" || exe === "gh" || exe === "npm") {
    args = tokens.slice(1);
  } else if (!path.isAbsolute(exe)) {
    const candidate = path.join(repoRoot, exe);
    exe = fs.existsSync(candidate) ? candidate : exe;
  }
  return { command: exe, args };
}

