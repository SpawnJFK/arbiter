#!/usr/bin/env node
// arbiter-strings: push source strings to Arbiter and pull translations back, from a laptop or CI.
// Zero dependencies (Node 18+: fetch, FormData, Blob). Configuration: arbiter.strings.json in the
// current directory (or --config <path>). The API token is read from the environment variable
// named by "tokenEnv" (default ARBITER_TOKEN); it is never written to disk or printed.
//
//   node cli/arbiter-strings.mjs push [--with-translations] [--archive-missing] [--tag <t>] [--branch <b>] [--dry-run]
//   node cli/arbiter-strings.mjs pull [--lang <l>] [--min-state machine|reviewed|approved] [--fallback] [--branch <b>]
//   node cli/arbiter-strings.mjs release [--label <v>] [--draft] [--branch <b>]
//   node cli/arbiter-strings.mjs status
//
// Paths in "files" may use {lang} (pt-BR), {lang_} (pt_BR), {android} (pt-rBR) and {ios} (pt-BR).

import fs from "node:fs";
import path from "node:path";

const HELP = `arbiter-strings <push|pull|release|status> [options]

  push      upload the base-language file(s); --with-translations also uploads target files
            that exist; --archive-missing archives keys no longer in the file; --tag adds a tag
  pull      download every target language (or --lang) into the configured paths
  release   build and publish an OTA release (--draft to leave it unpublished)
  status    show the project's languages and progress

  --config <file>   default ./arbiter.strings.json
  --branch <name>   default from config, else main
  --dry-run         print what would happen, send nothing
`;

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const name = a.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith("--") && !["with-translations", "archive-missing", "fallback", "draft", "dry-run", "help"].includes(name)) {
        out[name] = next;
        i++;
      } else out[name] = true;
    } else out._.push(a);
  }
  return out;
}

function fail(msg) {
  console.error(`arbiter-strings: ${msg}`);
  process.exit(1);
}

function loadConfig(file) {
  if (!fs.existsSync(file)) fail(`config file not found: ${file}`);
  let cfg;
  try {
    cfg = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (e) {
    fail(`config file is not valid JSON: ${e.message}`);
  }
  for (const k of ["apiUrl", "projectId", "files"]) if (!cfg[k]) fail(`config is missing "${k}"`);
  if (!Array.isArray(cfg.files) || cfg.files.length === 0) fail(`"files" must be a non-empty array`);
  cfg.apiUrl = String(cfg.apiUrl).replace(/\/+$/, "");
  cfg.tokenEnv = cfg.tokenEnv || "ARBITER_TOKEN";
  cfg.root = path.dirname(path.resolve(file));
  return cfg;
}

export function expandPath(pattern, lang) {
  const [base, ...rest] = lang.split("-");
  const region = rest.find((p) => /^[A-Z]{2}$|^\d{3}$/.test(p));
  const android = region ? `${base}-r${region}` : lang;
  return pattern
    .replaceAll("{lang}", lang)
    .replaceAll("{lang_}", lang.replaceAll("-", "_"))
    .replaceAll("{android}", android)
    .replaceAll("{ios}", lang);
}

class Client {
  constructor(cfg) {
    this.base = `${cfg.apiUrl}/v1/strings/projects/${encodeURIComponent(cfg.projectId)}`;
    this.token = process.env[cfg.tokenEnv];
    if (!this.token) fail(`environment variable ${cfg.tokenEnv} is not set (an Arbiter API key)`);
  }
  async request(method, suffix, { query, body, form } = {}) {
    const url = new URL(this.base + suffix);
    for (const [k, v] of Object.entries(query || {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    const headers = { Authorization: `Bearer ${this.token}` };
    let payload;
    if (form) payload = form;
    else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(url, { method, headers, body: payload });
    if (!res.ok) {
      let msg = `${res.status} ${res.statusText}`;
      try {
        const j = await res.json();
        if (j?.error?.message) msg = `${res.status} ${j.error.code}: ${j.error.message}`;
      } catch {
        /* not JSON */
      }
      throw new Error(`${method} ${url.pathname}: ${msg}`);
    }
    return res;
  }
  async json(method, suffix, opts) {
    return (await this.request(method, suffix, opts)).json();
  }
}

async function cmdStatus(cfg, api) {
  const p = await api.json("GET", "");
  console.log(`${p.name} (${p.id}), base ${p.base_lang}, ${p.stats.keys} keys`);
  for (const [lang, s] of Object.entries(p.stats.languages)) {
    console.log(`  ${lang.padEnd(8)} ${String(s.progress).padStart(3)}%  approved ${s.approved}  reviewed ${s.reviewed}  machine ${s.machine}  untranslated ${s.untranslated}  blocked ${s.blocked}`);
  }
}

async function upload(api, cfg, file, lang, args, entry, isBase) {
  const full = path.resolve(cfg.root, file);
  if (!fs.existsSync(full)) {
    if (isBase) fail(`base file not found: ${file}`);
    return null;
  }
  if (args["dry-run"]) {
    console.log(`would push ${file} (${lang})`);
    return null;
  }
  const form = new FormData();
  form.set("file", new Blob([fs.readFileSync(full)]), path.basename(full));
  form.set("lang", lang);
  if (entry.format) form.set("format", entry.format);
  if (entry.namespace) form.set("namespace", entry.namespace);
  const branch = args.branch || cfg.branch;
  if (branch) form.set("branch", branch);
  if (isBase && args["archive-missing"]) form.set("archive_missing", "true");
  if (args.tag) form.set("tag", args.tag);
  const r = await api.json("POST", "/push", { form });
  console.log(
    `pushed ${file} (${r.lang}, ${r.format}): created ${r.created}, updated ${r.updated}, unchanged ${r.unchanged}, archived ${r.archived}, skipped ${r.skipped}, blocked ${r.blocked}`,
  );
  for (const w of r.warnings || []) console.log(`  warning: ${w}`);
  return r;
}

async function cmdPush(cfg, api, args) {
  const p = await api.json("GET", "");
  const total = cfg.files.length;
  let n = 0;
  for (const entry of cfg.files) {
    n++;
    console.log(`[${n}/${total}] ${entry.path}`);
    await upload(api, cfg, expandPath(entry.path, p.base_lang), p.base_lang, args, entry, true);
    if (args["with-translations"]) {
      for (const lang of cfg.langs || p.target_langs) {
        await upload(api, cfg, expandPath(entry.path, lang), lang, args, entry, false);
      }
    }
  }
}

async function cmdPull(cfg, api, args) {
  const p = await api.json("GET", "");
  const langs = args.lang ? [args.lang] : cfg.langs || p.target_langs;
  const jobs = [];
  for (const entry of cfg.files) for (const lang of langs) jobs.push({ entry, lang });
  let n = 0;
  for (const { entry, lang } of jobs) {
    n++;
    const target = path.resolve(cfg.root, expandPath(entry.path, lang));
    if (args["dry-run"]) {
      console.log(`[${n}/${jobs.length}] would pull ${lang} into ${path.relative(process.cwd(), target)}`);
      continue;
    }
    const res = await api.request("GET", "/pull", {
      query: {
        lang,
        format: entry.format,
        namespace: entry.namespace,
        branch: args.branch || cfg.branch,
        min_state: args["min-state"] || cfg.minState,
        fallback: args.fallback || cfg.fallback ? "true" : undefined,
      },
    });
    const data = Buffer.from(await res.arrayBuffer());
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, data);
    console.log(`[${n}/${jobs.length}] pulled ${lang} -> ${path.relative(process.cwd(), target)} (${data.length} bytes)`);
  }
}

async function cmdRelease(cfg, api, args) {
  const r = await api.json("POST", "/releases", {
    body: { version_label: args.label || undefined, branch: args.branch || cfg.branch || undefined, publish: !args.draft },
  });
  console.log(`release ${r.version_label} ${r.status}, ${r.key_count} keys, hash ${r.content_hash.slice(0, 12)}`);
  if (r.ota) for (const [lang, u] of Object.entries(r.ota.langs)) console.log(`  ${lang}: ${u.versioned}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args._[0];
  if (!cmd || args.help) {
    console.log(HELP);
    process.exit(cmd ? 0 : 1);
  }
  const cfg = loadConfig(path.resolve(args.config || "arbiter.strings.json"));
  const api = new Client(cfg);
  const commands = { push: cmdPush, pull: cmdPull, release: cmdRelease, status: cmdStatus };
  if (!commands[cmd]) fail(`unknown command ${cmd}\n\n${HELP}`);
  try {
    await commands[cmd](cfg, api, args);
  } catch (e) {
    fail(e.message);
  }
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith("arbiter-strings.mjs")) {
  await main();
}
