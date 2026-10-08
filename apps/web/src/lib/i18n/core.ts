// Isomorphic i18n core: ICU-lite message formatting, translator factory and locale-aware
// formatters. Messages are flat `{ "namespace.key": "text" }` catalogs; English (messages/en.json)
// is the source and the fallback for every missing key.
//
// Supported syntax (a subset of ICU MessageFormat, same as the backend placeholder check):
//   {name}                                   argument
//   {count, plural, =0 {none} one {# job} other {# jobs}}   plural (Intl.PluralRules), # = count
//   {kind, select, a {...} b {...} other {...}}            select
//   '{literal}'  quotes braces,  ''  is a literal apostrophe

export type Messages = Record<string, string>;
export type Vars = Record<string, string | number | boolean | null | undefined>;

export const SOURCE_LOCALE = "en";
export const LOCALE_COOKIE = "arbiter_locale";

type Node = string | { arg: string; kind: "simple" } | { arg: string; kind: "plural" | "select"; offset: number; options: Record<string, Node[]> } | { kind: "hash" };

const parsed = new Map<string, Node[]>();

function parse(msg: string): Node[] {
  const hit = parsed.get(msg);
  if (hit) return hit;
  let i = 0;
  function nodes(inPlural: boolean, untilBrace: boolean): Node[] {
    const out: Node[] = [];
    let buf = "";
    const flush = () => {
      if (buf) out.push(buf);
      buf = "";
    };
    while (i < msg.length) {
      const ch = msg[i];
      if (ch === "'") {
        if (msg[i + 1] === "'") {
          buf += "'";
          i += 2;
          continue;
        }
        if (msg[i + 1] === "{" || msg[i + 1] === "}" || (inPlural && msg[i + 1] === "#")) {
          const end = msg.indexOf("'", i + 1);
          buf += end < 0 ? msg.slice(i + 1) : msg.slice(i + 1, end);
          i = end < 0 ? msg.length : end + 1;
          continue;
        }
        buf += ch;
        i++;
        continue;
      }
      if (ch === "}" && untilBrace) {
        flush();
        return out;
      }
      if (ch === "#" && inPlural) {
        flush();
        out.push({ kind: "hash" });
        i++;
        continue;
      }
      if (ch === "{") {
        flush();
        i++;
        out.push(argument());
        continue;
      }
      buf += ch;
      i++;
    }
    flush();
    return out;
  }
  function word(): string {
    while (/\s/.test(msg[i] ?? "")) i++;
    let w = "";
    while (i < msg.length && !/[\s,{}]/.test(msg[i])) w += msg[i++];
    while (/\s/.test(msg[i] ?? "")) i++;
    return w;
  }
  function argument(): Node {
    const arg = word();
    if (msg[i] === "}") {
      i++;
      return { arg, kind: "simple" };
    }
    if (msg[i] === ",") i++;
    const type = word();
    if (msg[i] === ",") i++;
    if (type !== "plural" && type !== "select") {
      // Unknown formatter (number, date...): treat as a simple argument; skip its style.
      let depth = 1;
      while (i < msg.length && depth > 0) {
        if (msg[i] === "{") depth++;
        if (msg[i] === "}") depth--;
        i++;
      }
      return { arg, kind: "simple" };
    }
    const options: Record<string, Node[]> = {};
    let offset = 0;
    for (;;) {
      const sel = word();
      if (!sel) break;
      if (sel.startsWith("offset:")) {
        offset = Number(sel.slice(7)) || 0;
        continue;
      }
      if (msg[i] !== "{") break;
      i++;
      options[sel] = nodes(type === "plural", true);
      i++; // closing }
      while (/\s/.test(msg[i] ?? "")) i++;
      if (msg[i] === "}") break;
    }
    if (msg[i] === "}") i++;
    return { arg, kind: type, offset, options };
  }
  const out = nodes(false, false);
  parsed.set(msg, out);
  return out;
}

const pluralRules = new Map<string, Intl.PluralRules>();
function pluralCategory(locale: string, n: number): string {
  let pr = pluralRules.get(locale);
  if (!pr) {
    try {
      pr = new Intl.PluralRules(locale);
    } catch {
      pr = new Intl.PluralRules("en");
    }
    pluralRules.set(locale, pr);
  }
  return pr.select(n);
}

function render(nodes: Node[], vars: Vars, locale: string, hash: number | null): string {
  let out = "";
  for (const n of nodes) {
    if (typeof n === "string") out += n;
    else if (n.kind === "hash") out += hash === null ? "#" : new Intl.NumberFormat(locale).format(hash);
    else if (n.kind === "simple") {
      const v = vars[n.arg];
      out += v === undefined || v === null ? `{${n.arg}}` : typeof v === "number" ? new Intl.NumberFormat(locale).format(v) : String(v);
    } else if (n.kind === "plural") {
      const raw = Number(vars[n.arg] ?? 0);
      const value = raw - n.offset;
      const branch = n.options[`=${raw}`] ?? n.options[pluralCategory(locale, value)] ?? n.options.other ?? [];
      out += render(branch, vars, locale, value);
    } else {
      const key = String(vars[n.arg] ?? "other");
      out += render(n.options[key] ?? n.options.other ?? [], vars, locale, hash);
    }
  }
  return out;
}

export function formatMessage(message: string, vars: Vars = {}, locale = SOURCE_LOCALE): string {
  if (!message.includes("{") && !message.includes("'")) return message;
  try {
    return render(parse(message), vars, locale, null);
  } catch {
    return message;
  }
}

export interface Translator {
  (key: string, vars?: Vars): string;
  /** Whether the key exists in the active catalog (or English). */
  has: (key: string) => boolean;
  /** Label for an enum value (snake_case): `enum.<value>`, falling back to a humanized value. */
  enumLabel: (value: string | null | undefined) => string;
  locale: string;
}

function humanizeValue(s: string): string {
  const x = s.replace(/_/g, " ");
  return x.charAt(0).toUpperCase() + x.slice(1);
}

/** `messages` are the active locale's overrides; `source` is English. Missing keys fall back to English, then to the key. */
export function createTranslator(locale: string, source: Messages, messages: Messages = {}): Translator {
  const t = ((key: string, vars?: Vars) => {
    const msg = messages[key] ?? source[key];
    if (msg === undefined) return key;
    return formatMessage(msg, vars, messages[key] !== undefined ? locale : SOURCE_LOCALE);
  }) as Translator;
  t.has = (key) => key in messages || key in source;
  t.enumLabel = (value) => {
    if (!value) return "–";
    const k = `enum.${value}`;
    return t.has(k) ? t(k) : humanizeValue(value);
  };
  t.locale = locale;
  return t;
}

/** Marks a string as a message key (for keys stored in data and translated later). Used by i18n:check. */
export function k<T extends string>(key: T): T {
  return key;
}
