#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { hash, inside, readJSON } from "./common.mjs";
import { evaluateCommand } from "./guard.mjs";
import { forbiddenTools, isCommercial, loadProject, pinnedNodeMajor, storagePolicy } from "./project.mjs";
/**
 * @param {string} [startDir]
 */
export function runDoctor(startDir = process.cwd()) {
  const ctx = loadProject(startDir);
  /** @type {Array<{ bucket: string, severity: "WARNING"|"BROKEN", message: string }>} */
  const findings = [];

  const lockPath = inside(ctx.root, ".hyperpower/core/core.lock.json");
  if (!fs.existsSync(lockPath)) {
    findings.push({ bucket: "core integrity", severity: "BROKEN", message: "missing core.lock.json" });
  } else {
    const lock = readJSON(lockPath);
    const coreDir = inside(ctx.root, ".hyperpower/core");
    for (const [rel, expected] of Object.entries(lock.files ?? {})) {
      const filePath = path.join(coreDir, rel);
      if (!fs.existsSync(filePath)) {
        findings.push({ bucket: "core integrity", severity: "BROKEN", message: `missing core file: ${rel}` });
        continue;
      }
      const actual = hash(fs.readFileSync(filePath));
      if (actual !== expected) {
        findings.push({ bucket: "core integrity", severity: "BROKEN", message: `hash mismatch: ${rel}` });
      }
    }
    const onDisk = listCoreFiles(coreDir).filter((f) => f !== "core.lock.json");
    for (const rel of onDisk) {
      if (!(rel in (lock.files ?? {}))) {
        findings.push({ bucket: "core integrity", severity: "BROKEN", message: `unlocked core file: ${rel}` });
      }
    }
  }

  /** @type {Array<{ bucket: string, message: string }>} */
  const verified = [];
  const nodeMajor = Number(process.versions.node.split(".")[0]);
  if (nodeMajor !== pinnedNodeMajor(ctx)) {
    findings.push({
      bucket: "runtime pin",
      severity: "BROKEN",
      message: `Node major ${nodeMajor} != pinned ${pinnedNodeMajor(ctx)}`,
    });
  } else {
    verified.push({
      bucket: "runtime pin",
      message: `VERIFIED: Node major ${nodeMajor} matches pinned ${pinnedNodeMajor(ctx)}`,
    });
  }

  const policy = storagePolicy(ctx);
  if (policy?.current && policy?.intendedRepoRoot) {
    const current = path.resolve(String(policy.current));
    const intended = path.resolve(String(policy.intendedRepoRoot));
    if (current !== intended) {
      const behaviour = String(policy.doctorBehaviour ?? "");
      const severity = behaviour.toLowerCase().includes("warn") ? "WARNING" : "BROKEN";
      findings.push({
        bucket: "storage policy",
        severity,
        message: `repo at ${current}; intended ${intended} (${policy.status ?? "unknown"})`,
      });
    }
  }

  const registryPath = inside(ctx.root, ".hyperpower/tools/registry.json");
  if (fs.existsSync(registryPath) && isCommercial(ctx)) {
    const reg = readJSON(registryPath);
    for (const tool of reg.tools ?? []) {
      if (tool.commercialUsePermitted === false) {
        findings.push({
          bucket: "tool licences",
          severity: "BROKEN",
          message: `tool ${tool.name} licence ${tool.licence ?? "unknown"} not permitted for commercial use`,
        });
      }
    }
  }

  for (const forbidden of forbiddenTools(ctx)) {
    const name = typeof forbidden === "string" ? forbidden : forbidden.name;
    if (!name) continue;
    const hits = scanForbiddenReference(ctx.root, name);
    if (hits.length > 0) {
      findings.push({
        bucket: "tool licences",
        severity: "BROKEN",
        message: `forbidden tool ${name} referenced in ${hits.slice(0, 3).join(", ")}${hits.length > 3 ? "…" : ""}`,
      });
    }
  }

  const deny = evaluateCommand("git reset --hard", { root: ctx.root, policy });
  const allow = evaluateCommand("git status --short", { root: ctx.root, policy });
  if (deny.allow || !allow.allow) {
    findings.push({
      bucket: "guard proof",
      severity: "BROKEN",
      message: "guard did not deny destructive git or allow safe git status",
    });
  }

  const graphifyBin = inside(ctx.root, ".hyperpower/tools/bin/graphify.exe");
  const graphifyHook = inside(ctx.root, "scripts/graphify-pre-push-hook.mjs");
  if (!fs.existsSync(graphifyBin)) {
    findings.push({
      bucket: "graphify guard",
      severity: "BROKEN",
      message: "graphify CLI missing at .hyperpower/tools/bin/graphify.exe, pre-push guard would SKIP",
    });
  } else if (fs.existsSync(graphifyHook)) {
    const probe = spawnSync(process.execPath, [graphifyHook], {
      cwd: ctx.root,
      encoding: "utf8",
      env: { ...process.env, GIT_HOOK_GRAPHIFY: graphifyBin },
      windowsHide: true,
    });
    const hookOut = `${probe.stderr ?? ""}${probe.stdout ?? ""}`;
    if (/skipping index check|not installed/i.test(hookOut)) {
      findings.push({
        bucket: "graphify guard",
        severity: "BROKEN",
        message: "graphify pre-push guard SKIPPED (not passed), hook output indicates skip",
      });
    } else if (/index fresh/i.test(hookOut)) {
      verified.push({ bucket: "graphify guard", message: "VERIFIED: pre-push hook reports index fresh" });
    } else if (/extract failed|update failed|allowing push \(soft guard\)/i.test(hookOut)) {
      findings.push({
        bucket: "graphify guard",
        severity: "BROKEN",
        message: "graphify pre-push guard failed soft path, index not verified fresh",
      });
    } else {
      findings.push({
        bucket: "graphify guard",
        severity: "BROKEN",
        message: "graphify pre-push hook did not report index fresh (ambiguous output)",
      });
    }
  }

  const broken = findings.filter((f) => f.severity === "BROKEN");
  const warnings = findings.filter((f) => f.severity === "WARNING");
  return { findings, verified, broken, warnings, exitCode: broken.length > 0 ? 1 : 0 };
}

/**
 * @param {string} coreDir
 */
function listCoreFiles(coreDir) {
  const out = [];
  for (const name of fs.readdirSync(coreDir)) {
    if (name.endsWith(".mjs") || name.endsWith(".json")) out.push(name);
  }
  return out.sort();
}

/**
 * @param {string} root
 * @param {string} name
 */
function scanForbiddenReference(root, name) {
  const hits = [];
  const targets = [
    path.join(root, "package.json"),
    path.join(root, "package-lock.json"),
    path.join(root, "scripts"),
    path.join(root, "src"),
    path.join(root, ".githooks"),
  ];
  const re = new RegExp(`\\b${escapeReg(name)}\\b`, "i");
  for (const target of targets) {
    if (!fs.existsSync(target)) continue;
    const st = fs.statSync(target);
    if (st.isFile()) {
      if (re.test(fs.readFileSync(target, "utf8"))) hits.push(path.relative(root, target).replace(/\\/g, "/"));
    } else {
      const skipDir = new Set(["node_modules"]);
      walk(target, (file) => {
        if (!/\.(json|mjs|js|ts|tsx)$/i.test(file)) return;
        if (re.test(fs.readFileSync(file, "utf8"))) hits.push(path.relative(root, file).replace(/\\/g, "/"));
      }, skipDir);
    }
  }
  return hits;
}

function escapeReg(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * @param {string} dir
 * @param {(file: string) => void} fn
 * @param {Set<string>} skipDir
 */
function walk(dir, fn, skipDir) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (skipDir.has(ent.name)) continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, fn, skipDir);
    else fn(p);
  }
}

/**
 * @param {string} [startDir]
 */
export function printDoctor(startDir = process.cwd()) {
  const result = runDoctor(startDir);
  console.log(JSON.stringify(result, null, 2));
  return result;
}
