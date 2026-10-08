// npm run i18n:check
// Verifies messages/en.json against the source: every key used in src/ exists (missing keys fail),
// every key in en.json is used (unused keys fail), and every message parses as ICU-lite.
//
// A key counts as used when it appears as a literal in t("..."), t.has("...") or k("..."), or
// matches a dynamic template such as t(`tier.${x}.label`) (any `prefix.${...}` template whose
// static parts look like a key), or is quoted verbatim anywhere in src/ (keys picked by a
// conditional or stored in a map). `enum.*` keys are used through t.enumLabel(value).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(ROOT, "src");
const en = JSON.parse(fs.readFileSync(path.join(ROOT, "messages/en.json"), "utf8"));
const keys = Object.keys(en);

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx|mjs)$/.test(e.name)) out.push(p);
  }
  return out;
}

const literal = new Map(); // key -> first "file:line"
const dynamic = []; // { re, where }
const KEY_RE = /^[a-z][A-Za-z0-9_]*(\.[A-Za-z0-9_-]+)+$/;

for (const file of walk(SRC)) {
  if (file.includes(`${path.sep}lib${path.sep}mock${path.sep}`)) continue;
  const text = fs.readFileSync(file, "utf8");
  const rel = path.relative(ROOT, file);
  const where = (idx) => `${rel}:${text.slice(0, idx).split("\n").length}`;
  for (const m of text.matchAll(/(?<!\w)(?:t|k|t\.has)\(\s*"([^"]+)"/g)) {
    if (!literal.has(m[1])) literal.set(m[1], where(m.index));
  }
  // Keys passed through variables or conditionals (t(cond ? "a.b" : "a.c")) count when quoted verbatim.
  for (const m of text.matchAll(/"([a-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_-]+)+)"/g)) {
    if (m[1] in en && !literal.has(m[1])) literal.set(m[1], where(m.index));
  }
  for (const m of text.matchAll(/`([a-z][A-Za-z0-9_.]*\.)\$\{[^}`]+\}((?:\.[A-Za-z0-9_]+)*)`/g)) {
    const re = new RegExp(`^${m[1].replace(/\./g, "\\.")}[^.]+${m[2].replace(/\./g, "\\.")}$`);
    dynamic.push({ re, where: where(m.index) });
  }
}
dynamic.push({ re: /^enum\./, where: "t.enumLabel" });

const problems = [];
for (const [key, at] of literal) {
  if (!KEY_RE.test(key)) continue; // not a message key (e.g. t("x") on an unrelated function)
  if (!(key in en)) problems.push(`missing  ${key}  (${at})`);
}
for (const key of keys) {
  if (literal.has(key)) continue;
  if (dynamic.some((d) => d.re.test(key))) continue;
  problems.push(`unused   ${key}`);
}

// ICU-lite sanity: balanced braces outside quotes, plural/select have an "other" branch.
for (const [key, msg] of Object.entries(en)) {
  if (typeof msg !== "string") {
    problems.push(`invalid  ${key}  (not a string)`);
    continue;
  }
  let depth = 0;
  let quoted = false;
  for (let i = 0; i < msg.length; i++) {
    const c = msg[i];
    if (c === "'") {
      if (msg[i + 1] === "'") i++;
      else if (quoted || /[{}#]/.test(msg[i + 1] ?? "")) quoted = !quoted;
      continue;
    }
    if (quoted) continue;
    if (c === "{") depth++;
    if (c === "}") depth--;
    if (depth < 0) break;
  }
  if (depth !== 0) problems.push(`invalid  ${key}  (unbalanced braces)`);
  for (const m of msg.matchAll(/\{\s*\w+\s*,\s*(plural|select)\s*,/g)) {
    if (!/\bother\s*\{/.test(msg.slice(m.index))) problems.push(`invalid  ${key}  (${m[1]} without "other")`);
  }
}

if (problems.length) {
  console.error(problems.sort().join("\n"));
  console.error(`\ni18n:check failed: ${problems.length} problem(s) in messages/en.json (${keys.length} keys).`);
  process.exit(1);
}
console.log(`i18n:check ok: ${keys.length} keys, ${literal.size} literal references, ${dynamic.length} dynamic patterns.`);
