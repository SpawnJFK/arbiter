#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { findRepoRoot, readJSON, inside } from "./common.mjs";

/**
 * @param {string} [startDir]
 */
export function loadProject(startDir = process.cwd()) {
  const root = findRepoRoot(startDir);
  const configPath = inside(root, "hyperpower.json");
  if (!fs.existsSync(configPath)) {
    throw new Error(`missing hyperpower.json at ${configPath}`);
  }
  let data;
  try {
    data = readJSON(configPath);
  } catch (e) {
    throw new Error(`hyperpower.json does not parse: ${e instanceof Error ? e.message : String(e)}`);
  }
  validateProject(data);
  return { root, config: data, configPath };
}

/**
 * @param {unknown} data
 */
function validateProject(data) {
  if (!data || typeof data !== "object") throw new Error("hyperpower.json must be an object");
  const o = /** @type {Record<string, unknown>} */ (data);
  const req = [
    ["schemaVersion", "number"],
    ["project", "string"],
    ["repo", "object"],
    ["runtime", "object"],
    ["capabilities", "array"],
    ["tools", "object"],
    ["gates", "object"],
  ];
  for (const [key, kind] of req) {
    if (!(key in o)) throw new Error(`hyperpower.json missing required field: ${key}`);
    if (kind === "number" && typeof o[key] !== "number") throw new Error(`${key} must be a number`);
    if (kind === "string" && typeof o[key] !== "string") throw new Error(`${key} must be a string`);
    if (kind === "object" && (typeof o[key] !== "object" || o[key] === null || Array.isArray(o[key]))) {
      throw new Error(`${key} must be an object`);
    }
    if (kind === "array" && !Array.isArray(o[key])) {
      throw new Error(`${key} must be an array`);
    }
  }
  const repo = /** @type {Record<string, unknown>} */ (o.repo);
  if (typeof repo.defaultBranch !== "string") throw new Error("repo.defaultBranch is required");
  const runtime = /** @type {Record<string, unknown>} */ (o.runtime);
  const node = runtime.node;
  if (!node || typeof node !== "object") throw new Error("runtime.node is required");
  if (typeof /** @type {Record<string, unknown>} */ (node).major !== "number") {
    throw new Error("runtime.node.major is required");
  }
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function projectName(ctx) {
  return ctx.config.project;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function displayName(ctx) {
  return ctx.config.displayName ?? ctx.config.project;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function defaultBranch(ctx) {
  return ctx.config.repo.defaultBranch;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function pinnedNodeMajor(ctx) {
  return ctx.config.runtime.node.major;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function devPort(ctx) {
  return ctx.config.runtime.devPort ?? 3000;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function storagePolicy(ctx) {
  return ctx.config.storagePolicy ?? null;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function requiredTools(ctx) {
  return ctx.config.tools?.required ?? [];
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function forbiddenTools(ctx) {
  return ctx.config.tools?.forbidden ?? [];
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function isCommercial(ctx) {
  return Boolean(ctx.config.commercial);
}

/**
 * @param {ReturnType<typeof loadProject>} ctx
 * @param {"phase"|"verticalSlice"|"launch"} gateKind
 */
export function requiredEvidenceTier(ctx, gateKind) {
  const tier = ctx.config.gates?.evidenceTier?.[gateKind];
  if (!tier) throw new Error(`unknown gate kind: ${gateKind}`);
  return tier;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function shipScript(ctx) {
  const script = ctx.config.gates?.shipScript;
  if (!script || typeof script !== "string") throw new Error("gates.shipScript is required");
  return script;
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function phasesConfig(ctx) {
  return ctx.config.phases ?? {};
}

/**
 * @param {ReturnType<typeof loadProject>} ctx
 * @param {string} phaseId
 */
export function phaseEntry(ctx, phaseId) {
  const phases = phasesConfig(ctx);
  const entry = phases[phaseId];
  if (!entry || typeof entry !== "object") throw new Error(`unknown phase: ${phaseId}`);
  return /** @type {Record<string, unknown>} */ (entry);
}

/** @param {ReturnType<typeof loadProject>} ctx */
export function beadsBinary(ctx) {
  const fromRegistry = toolInstallPath(ctx, "beads");
  if (fromRegistry) return fromRegistry;
  const fallback = inside(ctx.root, ".hyperpower/tools/bin/bd.exe");
  if (fs.existsSync(fallback)) return fallback;
  const alt = inside(ctx.root, ".hyperpower/tools/bin/bd");
  if (fs.existsSync(alt)) return alt;
  throw new Error("beads CLI (bd) not installed");
}

/**
 * @param {ReturnType<typeof loadProject>} ctx
 * @param {string} toolName
 */
function toolInstallPath(ctx, toolName) {
  const regPath = inside(ctx.root, ".hyperpower/tools/registry.json");
  if (!fs.existsSync(regPath)) return null;
  const reg = readJSON(regPath);
  const entry = (reg.tools ?? []).find((t) => t.name === toolName || t.name === `${toolName}-scanner`);
  if (!entry?.installPath) return null;
  const abs = inside(ctx.root, entry.installPath);
  return fs.existsSync(abs) ? abs : null;
}
