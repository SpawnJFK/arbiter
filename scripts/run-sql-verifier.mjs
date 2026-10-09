#!/usr/bin/env node
/**
 * HYPERPOWER sql verifier runner. Called by .hyperpower/core/verify.mjs for ledger records
 * with verifier.kind "sql". Read-only by construction: the statement is checked here AND runs
 * in a read-only transaction.
 *
 * stdin: JSON { query, expect, params? }
 *   expect: { rowCount?, countGte?, scalarEquals?, rows? }
 *   params: { name: value } referenced in the query as $name
 * exit:   0 VERIFIED, 1 BROKEN, 2 STALE (could not run, proves nothing)
 *
 * Connection: ARBITER_DATABASE_URL from the process, else from services/api/.env, else the
 * local dev default. The query runs through psycopg in services/api/.venv, so no Node database
 * driver is needed. Never prints connection strings.
 */
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { apiPython, root } from "./lib/proc.mjs";

const EXIT = { VERIFIED: 0, BROKEN: 1, STALE: 2 };

function fail(msg) {
  const tagged = /^(STALE|BROKEN):/.test(msg) ? msg : `BROKEN: ${msg}`;
  console.error(tagged);
  process.exit(tagged.startsWith("STALE:") ? EXIT.STALE : EXIT.BROKEN);
}

function envFileValue(file, key) {
  let raw;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    return undefined;
  }
  for (const line of raw.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq === -1 || t.slice(0, eq).trim() !== key) continue;
    let v = t.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    return v || undefined;
  }
  return undefined;
}

/** @param {string} sql */
function assertReadOnlySql(sql) {
  const stripped = sql
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/--[^\n]*/g, " ")
    .trim()
    .replace(/;\s*$/, "");
  if (stripped.includes(";")) throw new Error("STALE: only a single SQL statement is allowed");
  const forbidden =
    /\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXECUTE|CALL|COPY|MERGE|REPLACE|VACUUM|REINDEX|CLUSTER|COMMENT|SECURITY|SET\s+ROLE|LOCK)\b/i;
  if (forbidden.test(stripped)) throw new Error("STALE: query is not read-only");
  if (!/^(WITH|SELECT)\b/i.test(stripped)) throw new Error("STALE: query must begin with SELECT or WITH");
  return stripped;
}

function compareExpect(expect, rows) {
  if (expect.rowCount !== undefined && rows.length !== Number(expect.rowCount)) {
    throw new Error(`BROKEN: rowCount ${rows.length} !== ${expect.rowCount}`);
  }
  if (expect.countGte !== undefined) {
    const val = Number(Object.values(rows[0] ?? {})[0] ?? 0);
    if (val < Number(expect.countGte)) throw new Error(`BROKEN: count ${val} < ${expect.countGte}`);
  }
  if (expect.scalarEquals !== undefined) {
    const val = Object.values(rows[0] ?? {})[0];
    if (val !== expect.scalarEquals && String(val) !== String(expect.scalarEquals)) {
      throw new Error(`BROKEN: scalar ${val} !== ${expect.scalarEquals}`);
    }
  }
  if (expect.rows !== undefined && JSON.stringify(rows) !== JSON.stringify(expect.rows)) {
    throw new Error("BROKEN: rows mismatch");
  }
}

// Runs one statement read-only; $name placeholders become psycopg %(name)s parameters.
const PY = `
import json, re, sys
import psycopg
from psycopg.rows import dict_row
body = json.load(sys.stdin)
url = body["url"].replace("postgresql+psycopg://", "postgresql://", 1)
params = body.get("params") or {}
sql = body["query"].replace("%", "%%")
def sub(m):
    name = m.group(1)
    if name not in params:
        raise SystemExit("STALE: missing param " + name)
    return "%(" + name + ")s"
sql = re.sub(r"\\$(\\w+)", sub, sql)
try:
    conn = psycopg.connect(url, connect_timeout=10, row_factory=dict_row)
except Exception as e:
    raise SystemExit("STALE: cannot connect: " + type(e).__name__)
with conn:
    conn.read_only = True
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
print(json.dumps(rows, default=str))
`;

const body = (() => {
  try {
    return JSON.parse(readFileSync(0, "utf8"));
  } catch {
    return null;
  }
})();
if (!body?.query) fail("STALE: missing query");
if (body.expect === undefined || body.expect === null) fail("STALE: missing expect");

let sql;
try {
  sql = assertReadOnlySql(String(body.query));
} catch (e) {
  fail(e instanceof Error ? e.message : String(e));
}

const py = apiPython();
if (!py) fail("STALE: services/api/.venv is missing (psycopg runs the query)");
const url =
  process.env.ARBITER_DATABASE_URL ??
  envFileValue(path.join(root, "services", "api", ".env"), "ARBITER_DATABASE_URL") ??
  "postgresql+psycopg://arbiter:arbiter@localhost:5432/arbiter";

const r = spawnSync(py, ["-I", "-c", PY], {
  input: JSON.stringify({ url, query: sql, params: body.params ?? {} }),
  encoding: "utf8",
  windowsHide: true,
});
if (r.status !== 0) {
  const msg = (r.stderr || r.stdout || "").trim().split(/\r?\n/).pop() ?? "query failed";
  fail(/^(STALE|BROKEN):/.test(msg) ? msg : `BROKEN: ${msg}`);
}
let rows;
try {
  rows = JSON.parse(r.stdout);
} catch {
  fail("BROKEN: could not parse query result");
}
try {
  compareExpect(body.expect, rows);
} catch (e) {
  fail(e instanceof Error ? e.message : String(e));
}
console.log(JSON.stringify({ outcome: "VERIFIED", rows: rows.length }));
process.exit(EXIT.VERIFIED);
