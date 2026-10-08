// Translation exchange formats for /admin/languages: export the English catalog with a
// locale's current translations, and parse files translators send back.
//
//   JSON   flat object: { "<key>": { "source": "<English>", "target": "<translation>" } }
//          (exporting "en" gives the plain catalog { "<key>": "<English>" })
//   CSV    key,source_en,target (RFC 4180, UTF-8 with BOM so spreadsheet apps detect it)
//   XLIFF  2.1, srcLang="en" trgLang="<locale>", one <unit id="<key>"> per message
//
// Import accepts all three (and XLIFF 1.2 <trans-unit>), detected from the content.
import type { Messages } from "./core";

export type ExportFormat = "json" | "csv" | "xliff";
export const EXPORT_FORMATS: ExportFormat[] = ["json", "csv", "xliff"];

export interface ParsedImport {
  format: ExportFormat;
  /** key -> translation; units without a translation are left out (never sent as deletions). */
  messages: Messages;
  /** Keys in the file that the English catalog does not have (skipped). */
  unknown: string[];
  /** Units present in the file without a translation. */
  empty: number;
}

export class ImportError extends Error {}

// ---- export ----------------------------------------------------------------------------

const xmlEscape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function csvCell(s: string): string {
  return /[",\r\n]/.test(s) || /^\s|\s$/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function exportCatalog(format: ExportFormat, locale: string, source: Messages, targets: Messages, isSource: boolean): { body: string; contentType: string; filename: string } {
  const keys = Object.keys(source).sort();
  const base = `arbiter-ui-${locale}`;
  if (format === "json") {
    const out: Record<string, unknown> = {};
    for (const k of keys) out[k] = isSource ? source[k] : { source: source[k], target: targets[k] ?? "" };
    return { body: JSON.stringify(out, null, 2) + "\n", contentType: "application/json; charset=utf-8", filename: `${base}.json` };
  }
  if (format === "csv") {
    const lines = ["key,source_en,target", ...keys.map((k) => [k, source[k], isSource ? "" : targets[k] ?? ""].map(csvCell).join(","))];
    return { body: "﻿" + lines.join("\r\n") + "\r\n", contentType: "text/csv; charset=utf-8", filename: `${base}.csv` };
  }
  const units = keys.map((k) => {
    const target = isSource ? undefined : targets[k];
    const state = target ? "translated" : "initial";
    return [
      `    <unit id="${xmlEscape(k)}">`,
      `      <segment state="${state}">`,
      `        <source>${xmlEscape(source[k])}</source>`,
      ...(target ? [`        <target>${xmlEscape(target)}</target>`] : []),
      "      </segment>",
      "    </unit>",
    ].join("\n");
  });
  const trg = isSource ? "" : ` trgLang="${xmlEscape(locale)}"`;
  const body = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.1" srcLang="en"${trg}>`,
    `  <file id="arbiter-ui" original="messages/en.json">`,
    ...units,
    "  </file>",
    "</xliff>",
    "",
  ].join("\n");
  return { body, contentType: "application/xliff+xml; charset=utf-8", filename: `${base}.xlf` };
}

// ---- import ----------------------------------------------------------------------------

function xmlText(raw: string): string {
  // Inline markup is not used by the catalog; keep the text content of any element that slipped in.
  const noCdata = raw.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, (_, c: string) => xmlEscape(c));
  return noCdata
    .replace(/<[^>]+>/g, "")
    .replace(/&#x([0-9a-f]+);/gi, (_, h: string) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d: string) => String.fromCodePoint(Number(d)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function attr(tag: string, name: string): string | null {
  const m = new RegExp(`\\s${name}\\s*=\\s*("([^"]*)"|'([^']*)')`).exec(tag);
  return m ? xmlText(m[2] ?? m[3] ?? "") : null;
}

function parseXliff(text: string): Array<[string, string | null]> {
  if (!/<xliff[\s>]/.test(text)) throw new ImportError("not an XLIFF file");
  const out: Array<[string, string | null]> = [];
  // XLIFF 2.x <unit id> (segments concatenated) and 1.2 <trans-unit id|resname>.
  for (const m of text.matchAll(/<(unit|trans-unit)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
    const key = m[1] === "trans-unit" ? attr(m[2], "resname") ?? attr(m[2], "id") : attr(m[2], "id");
    if (!key) continue;
    const targets = [...m[3].matchAll(/<target\b[^>]*>([\s\S]*?)<\/target>/g)].map((x) => xmlText(x[1]));
    out.push([key, targets.length ? targets.join("") : null]);
  }
  return out;
}

function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  if (quoted) throw new ImportError("unterminated quote in the CSV file");
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((x) => x.trim() !== ""));
}

function parseCsv(text: string): Array<[string, string | null]> {
  const rows = parseCsvRows(text);
  if (!rows.length) return [];
  const header = rows[0].map((h) => h.trim().toLowerCase());
  const hasHeader = header.includes("key");
  const keyCol = hasHeader ? header.indexOf("key") : 0;
  const targetCol = hasHeader ? (header.includes("target") ? header.indexOf("target") : header.length - 1) : rows[0].length - 1;
  if (targetCol === keyCol) throw new ImportError("the CSV file needs a key column and a target column");
  return rows.slice(hasHeader ? 1 : 0).map((r) => [r[keyCol]?.trim() ?? "", r[targetCol] ?? null]);
}

function parseJson(text: string): Array<[string, string | null]> {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new ImportError("the JSON file does not parse");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new ImportError("the JSON file must be an object of key: translation");
  const root = data as Record<string, unknown>;
  // Accept {"messages": {...}} wrappers as well.
  const obj = root.messages && typeof root.messages === "object" && !Array.isArray(root.messages) ? (root.messages as Record<string, unknown>) : root;
  const out: Array<[string, string | null]> = [];
  const visit = (o: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(o)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (typeof v === "string") out.push([key, v]);
      else if (v && typeof v === "object" && !Array.isArray(v)) {
        const rec = v as Record<string, unknown>;
        if ("target" in rec || "source" in rec || "translation" in rec) {
          const tv = rec.target ?? rec.translation;
          out.push([key, typeof tv === "string" ? tv : null]);
        } else visit(rec, key);
      }
    }
  };
  visit(obj, "");
  return out;
}

export function detectFormat(text: string, filename = ""): ExportFormat {
  const t = text.replace(/^﻿/, "").trimStart();
  if (/\.(xlf|xliff)$/i.test(filename) || t.startsWith("<")) return "xliff";
  if (/\.json$/i.test(filename) || t.startsWith("{")) return "json";
  return "csv";
}

/** Parse an uploaded translation file against the English catalog. */
export function parseImport(raw: string, filename: string, source: Messages): ParsedImport {
  const text = raw.replace(/^﻿/, "");
  const format = detectFormat(text, filename);
  const pairs = format === "xliff" ? parseXliff(text) : format === "json" ? parseJson(text) : parseCsv(text);
  const messages: Messages = {};
  const unknown: string[] = [];
  let empty = 0;
  for (const [key, value] of pairs) {
    if (!key) continue;
    if (!(key in source)) {
      unknown.push(key);
      continue;
    }
    if (value === null || value.trim() === "") {
      empty++;
      continue;
    }
    messages[key] = value;
  }
  return { format, messages, unknown, empty };
}
