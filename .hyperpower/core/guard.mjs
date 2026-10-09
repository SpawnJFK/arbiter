#!/usr/bin/env node
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadProject, storagePolicy } from "./project.mjs";

/**
 * @param {string} commandText
 * @param {{ root?: string, policy?: ReturnType<typeof storagePolicy> }} [ctx]
 */
export function evaluateCommand(commandText, ctx = {}) {
  const text = String(commandText ?? "").trim();
  if (!text) {
    return deny("Empty command.", "Provide a concrete command to run.");
  }

  if (/\bgit\b[^;\n]*\breset\s+--hard\b/i.test(text)) {
    return deny(
      "Blocked: `git reset --hard` destroys uncommitted work.",
      "Use `git status`, `git stash`, or revert specific commits instead of reset --hard."
    );
  }
  if (/\bgit\b[^;\n]*\bclean\b[^;\n]*(-f|--force)/i.test(text) && /(-d|-x|--force)/i.test(text)) {
    return deny(
      "Blocked: destructive `git clean` with force flags.",
      "List untracked files with `git status` and remove only what you intend."
    );
  }
  if (/\bgit\b[^;\n]*\bpush\b[^;\n]*--force\b/i.test(text) || /\bgit\b[^;\n]*\bpush\b[^;\n]*\s-f\b/i.test(text)) {
    return deny(
      "Blocked: force push rewrites remote history.",
      "Use a normal push or open a PR; never force-push shared branches without explicit founder approval."
    );
  }

  if (
    /\brm\s+-rf\s+\/\b/i.test(text) ||
    /\brm\s+-rf\s+~\b/i.test(text) ||
    /\bdel\s+\/f\s+\/s\s+[a-z]:\\?\b/i.test(text) ||
    /\bformat-[a-z]+\b/i.test(text) ||
    /\bRemove-Item\b[^;\n]*-Recurse[^;\n]*-Force[^;\n]*(\\|\/|~|\$env:USERPROFILE|[a-z]:\\)/i.test(text)
  ) {
    return deny(
      "Blocked: recursive force deletion or drive formatting at a sensitive root.",
      "Delete only paths inside the project tree, one directory at a time, without force-at-root patterns."
    );
  }

  if (
    /(\bcurl\b|\bwget\b|\birm\b|\biwr\b|\binvoke-webrequest\b|\binvoke-restmethod\b)[^;\n]*\|\s*(sh|bash|zsh|pwsh|powershell|iex|invoke-expression)/i.test(
      text
    )
  ) {
    return deny(
      "Blocked: download-and-execute pipeline.",
      "Download to a file, inspect it, then run a known local script explicitly."
    );
  }

  if (/\b(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{10,}|ctx7sk-[A-Za-z0-9-]+)\b/.test(text)) {
    return deny(
      "Blocked: command text contains a literal credential-shaped token.",
      "Load secrets from environment or a gitignored file; never paste tokens into commands."
    );
  }

  const policy = ctx.policy ?? (ctx.root ? storagePolicy(loadProject(ctx.root)) : null);
  if (policy && policy.artifactRoot && !String(policy.status ?? "").includes("VIOLATION_ACCEPTED")) {
    const artifactRoot = path.resolve(String(policy.artifactRoot));
    const writeMatch = text.match(/(?:^|[\s|>]+\s*)([a-z]:\\[^\s|;&]+|\/[^\s|;&]+)/gi);
    if (writeMatch) {
      for (const raw of writeMatch) {
        const candidate = raw.trim().replace(/^[\s|>]+/, "");
        if (!/\.(log|json|png|jpg|zip|tar|gz|mp4|webm|pdf)$/i.test(candidate)) continue;
        try {
          const resolved = path.resolve(candidate);
          if (!resolved.startsWith(artifactRoot)) {
            return deny(
              "Blocked: heavy artifact path outside configured artifactRoot.",
              `Write large artifacts under artifactRoot (${policy.artifactRoot}) or update storagePolicy first.`
            );
          }
        } catch {
          /* ignore */
        }
      }
    }
  }

  return allow();
}

function allow() {
  return { allow: true, userMessage: null, agentMessage: null };
}

function deny(userMessage, agentMessage) {
  return { allow: false, userMessage, agentMessage };
}

/**
 * Hook entry: JSON on stdin { "command": "..." } -> JSON decision on stdout.
 */
export async function runHook() {
  try {
    const raw = await readStdin();
    const req = JSON.parse(raw);
    if (!req || typeof req !== "object" || typeof req.command !== "string") {
      writeDecision(
        deny("Invalid guard hook input.", "Hook payload must be JSON with a string `command` field.")
      );
      return;
    }
    let root;
    try {
      root = loadProject(process.cwd()).root;
    } catch {
      root = process.cwd();
    }
    writeDecision(evaluateCommand(req.command, { root }));
  } catch {
    writeDecision(deny("Invalid guard hook input.", "Hook payload must be valid JSON with a string `command` field."));
  }
}

function writeDecision(decision) {
  process.stdout.write(`${JSON.stringify(decision)}\n`);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => {
      data += c;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

const __filename = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runHook().then(() => process.exit(0));
}
