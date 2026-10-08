// Mock of the backend UI-localization endpoints (services/api arbiter/i18n.py):
//   GET    /i18n/locales                 public; admins also see disabled locales
//   GET    /i18n/messages/{locale}       public for enabled locales; admins any
//   PUT    /admin/i18n/locales/{locale}  {name, enabled?}
//   PUT    /admin/i18n/messages/{locale} {messages, mode: merge|replace, source?}
//   DELETE /admin/i18n/locales/{locale}
// English is the implicit source and is never stored.

type Loc = { name: string; enabled: boolean; created_at: string; messages: Map<string, { value: string; updated_at: string }> };
type Role = "admin" | "pm" | "client" | "reviewer" | null;

const SOURCE = "en";
const json = (data: unknown, status = 200) => Response.json(data, { status });
const err = (status: number, code: string, message: string, details: Record<string, unknown> = {}) =>
  Response.json({ error: { code, message, details } }, { status });

// A few German strings so the demo shows partial coverage and the English fallback.
const DE_SEED: Record<string, string> = {
  "app.layout.dashboard": "Übersicht",
  "app.layout.projects": "Projekte",
  "app.layout.newProject": "Neues Projekt",
  "app.layout.accounts": "Kunden",
  "app.layout.workflows": "Workflows",
  "app.layout.glossaries": "Glossare",
  "components.shell.signOut": "Abmelden",
  "admin.layout.languages": "Sprachen",
  "admin.layout.reviewers": "Prüfer",
};

function store(): Map<string, Loc> {
  const g = globalThis as unknown as { __arbiterMockI18n?: Map<string, Loc> };
  if (!g.__arbiterMockI18n) {
    const at = "2026-10-01T09:00:00+00:00";
    const m = new Map<string, Loc>();
    m.set("de", { name: "Deutsch", enabled: true, created_at: at, messages: new Map(Object.entries(DE_SEED).map(([k, v]) => [k, { value: v, updated_at: at }])) });
    m.set("fr", { name: "Français", enabled: false, created_at: at, messages: new Map([["app.layout.dashboard", { value: "Tableau de bord", updated_at: at }]]) });
    g.__arbiterMockI18n = m;
  }
  return g.__arbiterMockI18n;
}

/** BCP-47-ish normalisation, same shape as the backend's normalize_locale (de, pt-BR, sr-Latn-RS). */
function normalize(raw: string): string | null {
  const parts = raw.trim().replace(/_/g, "-").split("-").filter(Boolean);
  if (!parts.length || !/^[a-zA-Z]{2,3}$/.test(parts[0])) return null;
  return parts
    .map((p, i) => (i === 0 ? p.toLowerCase() : p.length === 4 ? p.charAt(0).toUpperCase() + p.slice(1).toLowerCase() : p.length <= 3 ? p.toUpperCase() : p))
    .join("-");
}

/** Top-level ICU argument names (mirrors arbiter.i18n.placeholders). */
export function placeholders(message: string): Set<string> {
  const out = new Set<string>();
  let depth = 0;
  for (let i = 0; i < message.length; i++) {
    const ch = message[i];
    if (ch === "'") {
      if (message[i + 1] === "'") {
        i++;
        continue;
      }
      if (message[i + 1] === "{" || message[i + 1] === "}") {
        const end = message.indexOf("'", i + 1);
        i = end < 0 ? message.length : end;
        continue;
      }
    } else if (ch === "{") {
      if (depth === 0) {
        const m = /^\s*([^\s,{}]+)/.exec(message.slice(i + 1));
        if (m) out.add(m[1]);
      }
      depth++;
    } else if (ch === "}") depth = Math.max(0, depth - 1);
  }
  return out;
}

function view(locale: string, l: Loc) {
  let last = l.created_at;
  for (const v of l.messages.values()) if (v.updated_at > last) last = v.updated_at;
  return { locale, name: l.name, enabled: l.enabled, message_count: l.messages.size, updated_at: last };
}

export function i18nRoute(method: string, parts: string[], role: Role, body: Record<string, unknown>): Response | null {
  const s = store();
  const admin = role === "admin";
  if (parts[0] === "i18n") {
    if (method !== "GET") return err(405, "method_not_allowed", "Method not allowed.");
    if (parts[1] === "locales" && parts.length === 2) {
      const items = [...s.entries()].filter(([, l]) => admin || l.enabled).sort(([a], [b]) => a.localeCompare(b));
      return json({ items: [{ locale: SOURCE, name: "English", enabled: true, message_count: null, updated_at: null }, ...items.map(([k, l]) => view(k, l))] });
    }
    if (parts[1] === "messages" && parts[2]) {
      const loc = normalize(parts[2]);
      if (!loc) return err(422, "validation_error", "invalid locale");
      if (loc === SOURCE) return json({ locale: SOURCE, messages: {} });
      const l = s.get(loc);
      if (!l || (!l.enabled && !admin)) return err(404, "not_found", `locale ${loc} is not available`);
      return json({ locale: loc, messages: Object.fromEntries([...l.messages.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, v.value])) });
    }
    return null;
  }
  if (parts[0] === "admin" && parts[1] === "i18n") {
    if (!admin) return err(403, "forbidden", "Admin only.");
    const loc = normalize(parts[3] ?? "");
    if (!loc) return err(422, "validation_error", "invalid locale");
    if (parts[2] === "locales" && method === "PUT") {
      if (loc === SOURCE) return err(422, "validation_error", "en is the source catalog; it lives in the web repo and is not stored here");
      const name = String(body.name ?? "").trim();
      if (!name) return err(422, "validation_error", "name is required");
      const l = s.get(loc);
      if (!l) s.set(loc, { name, enabled: Boolean(body.enabled), created_at: new Date().toISOString(), messages: new Map() });
      else {
        l.name = name;
        if (typeof body.enabled === "boolean") l.enabled = body.enabled;
      }
      return json(view(loc, s.get(loc)!));
    }
    if (parts[2] === "locales" && method === "DELETE") {
      if (!s.delete(loc)) return err(404, "not_found", `locale ${loc} not found`);
      return new Response(null, { status: 204 });
    }
    if (parts[2] === "messages" && method === "PUT") {
      if (loc === SOURCE) return err(422, "validation_error", "en is the source catalog; it lives in the web repo and is not stored here");
      const messages = (body.messages ?? {}) as Record<string, string>;
      const source = (body.source ?? null) as Record<string, string> | null;
      const mode = body.mode === "replace" ? "replace" : "merge";
      if (source) {
        const bad: Record<string, { expected: string[]; got: string[] }> = {};
        for (const [k, v] of Object.entries(messages)) {
          if (!v || !(k in source)) continue;
          const want = [...placeholders(source[k])].sort();
          const got = [...placeholders(v)].sort();
          if (want.join("\u0000") !== got.join("\u0000")) bad[k] = { expected: want, got };
        }
        if (Object.keys(bad).length) return err(422, "validation_error", "placeholders differ from the English source", { placeholders: bad });
      }
      if (!s.has(loc)) s.set(loc, { name: loc, enabled: false, created_at: new Date().toISOString(), messages: new Map() });
      const l = s.get(loc)!;
      const now = new Date().toISOString();
      let upserted = 0;
      let deleted = 0;
      for (const [k, v] of Object.entries(messages)) {
        const row = l.messages.get(k);
        if (v === "") {
          if (row) {
            l.messages.delete(k);
            deleted++;
          }
          continue;
        }
        if (!row || row.value !== v) {
          l.messages.set(k, { value: v, updated_at: now });
          upserted++;
        }
      }
      if (mode === "replace") {
        for (const k of [...l.messages.keys()]) {
          if (!(k in messages)) {
            l.messages.delete(k);
            deleted++;
          }
        }
      }
      return json({ locale: loc, upserted, deleted, total: l.messages.size });
    }
  }
  return null;
}
