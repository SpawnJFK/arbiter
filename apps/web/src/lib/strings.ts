// Software strings module (docs/api-contract.md "Software strings"): types, a typed client on
// the same transports as api.ts, and the placeholder helpers the key editor uses.

import { newIdempotencyKey, proxyTransport, type Query, type Transport } from "./api";
import type { ISODate, ListResponse } from "./types";

export type StringState = "untranslated" | "machine" | "reviewed" | "approved";
export type StringKind = "string" | "plural" | "array";
export type StringTier = "auto" | "ai_review" | "hybrid" | "full";
export const STRING_STATES: StringState[] = ["untranslated", "machine", "reviewed", "approved"];
export const STRING_PLATFORMS = ["web", "ios", "android", "flutter", "backend", "desktop", "other"] as const;

export interface LangStats {
  untranslated: number;
  machine: number;
  reviewed: number;
  approved: number;
  blocked: number;
  progress: number;
}

export interface StringProjectSettings {
  placeholder_style: string;
  plural_rules: Record<string, string[]>;
  human_review: boolean;
  release_min_state: Exclude<StringState, "untranslated">;
  fallback_to_base: boolean;
  private: boolean;
  default_format: string;
  engine: string | null;
}

export interface StringProject {
  id: string;
  name: string;
  public_id: string;
  base_lang: string;
  target_langs: string[];
  platforms: string[];
  tier: StringTier;
  settings: StringProjectSettings;
  has_distribution_token: boolean;
  ota_base: string;
  created_at: ISODate | null;
  stats?: { keys: number; archived: number; languages: Record<string, LangStats> };
}

export interface QaIssue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  blocking: boolean;
  form?: string;
}

export interface StringTranslation {
  value: string;
  forms: Record<string, string> | null;
  state: StringState;
  origin: string | null;
  engine: string | null;
  qe_score: number | null;
  qa: QaIssue[];
  blocked: boolean;
  needs_review: boolean;
  version: number;
  updated_by: string | null;
  updated_at: ISODate | null;
  branch_local: boolean;
}

export interface StringKey {
  id: string;
  namespace: string;
  name: string;
  kind: StringKind;
  description: string;
  screenshot_url: string | null;
  max_length: number | null;
  tags: string[];
  translatable: boolean;
  archived: boolean;
  branch_local: boolean;
  placeholders: string[];
  plural_forms: Record<string, string[]> | null;
  translations: Record<string, StringTranslation | null>;
}

export interface StringBranch {
  id: string;
  name: string;
  is_main: boolean;
  from_branch_id: string | null;
  created_at: ISODate | null;
  merged_at: ISODate | null;
  changes: number;
  new_keys: number;
}

export interface MergeConflict {
  key_id: string;
  key: string;
  lang: string;
  branch_value: string | Record<string, string> | null;
  main_value: string | Record<string, string> | null;
}

export interface StringBatch {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  mode: "translate" | "tm_only";
  langs: string[];
  total: number;
  done: number;
  progress: number;
  counts: Record<string, number>;
  review_job_id: string | null;
  error: string | null;
  created_at: ISODate | null;
  finished_at: ISODate | null;
}

export interface StringRelease {
  id: string;
  version_label: string;
  status: "draft" | "published";
  branch_id: string;
  langs: string[];
  content_hash: string;
  key_count: number;
  files: Record<string, Record<string, { sha256: string; bytes: number }>>;
  ota: {
    manifest: string;
    latest_manifest: string;
    langs: Record<string, { versioned: string; latest: string }>;
  } | null;
  created_at: ISODate | null;
  published_at: ISODate | null;
}

export interface StringFormat {
  name: string;
  label: string;
  extension: string;
  multilingual: boolean;
  bilingual: boolean;
}

export interface PushResult {
  format: string;
  lang: string;
  branch: string;
  keys_in_file: number;
  created: number;
  updated: number;
  unchanged: number;
  archived: number;
  skipped: number;
  blocked: number;
  warnings: string[];
}

export interface HistoryItem {
  id: string;
  lang: string;
  event: string;
  version: number;
  value: string;
  forms: Record<string, string> | null;
  state: string;
  actor_type: string;
  actor_id: string;
  at: ISODate | null;
}

export interface KeyQuery {
  branch?: string;
  q?: string;
  tag?: string;
  namespace?: string;
  lang?: string;
  state?: string;
  langs?: string;
  include_archived?: boolean;
  offset?: number;
  limit?: number;
}

export interface KeyInput {
  name: string;
  namespace?: string;
  kind?: StringKind;
  description?: string;
  max_length?: number | null;
  tags?: string[];
  screenshot_url?: string | null;
  value?: string;
  forms?: Record<string, string>;
}

const enc = encodeURIComponent;

export function createStringsApi(tr: Transport) {
  const base = (id: string) => `/strings/projects/${enc(id)}`;
  const get = <T>(path: string, query?: Query) => tr.request<T>("GET", path, { query });
  const send = <T>(method: string, path: string, body?: unknown, query?: Query, idem = false) =>
    tr.request<T>(method, path, { body, query, idempotencyKey: idem ? newIdempotencyKey() : undefined });
  return {
    downloadUrl: tr.downloadUrl,
    formats: () => get<{ items: StringFormat[] }>("/strings/formats"),
    projects: () => get<ListResponse<StringProject>>("/strings/projects", { limit: 200 }),
    project: (id: string) => get<StringProject>(base(id)),
    createProject: (body: {
      name: string;
      base_lang: string;
      target_langs: string[];
      platforms: string[];
      tier?: StringTier;
      settings?: Partial<StringProjectSettings>;
    }) => send<StringProject>("POST", "/strings/projects", body, undefined, true),
    updateProject: (id: string, body: Record<string, unknown>) => send<StringProject>("PATCH", base(id), body),
    keys: (id: string, q: KeyQuery) =>
      get<{ items: StringKey[]; total: number; next_offset: number | null; branch: StringBranch }>(`${base(id)}/keys`, { ...q }),
    createKey: (id: string, body: KeyInput, branch?: string) => send<StringKey>("POST", `${base(id)}/keys`, body, { branch }),
    updateKey: (id: string, keyId: string, body: Record<string, unknown>, branch?: string) =>
      send<StringKey>("PATCH", `${base(id)}/keys/${enc(keyId)}`, body, { branch }),
    setTranslation: (
      id: string,
      keyId: string,
      lang: string,
      body: { value?: string; forms?: Record<string, string>; state?: Exclude<StringState, "untranslated"> },
      branch?: string,
    ) => send<StringKey>("PUT", `${base(id)}/keys/${enc(keyId)}/translations/${enc(lang)}`, body, { branch }),
    clearTranslation: (id: string, keyId: string, lang: string, branch?: string) =>
      send<StringKey>("DELETE", `${base(id)}/keys/${enc(keyId)}/translations/${enc(lang)}`, undefined, { branch }),
    suggest: (id: string, keyId: string, lang: string, branch?: string) =>
      send<{ outcome: string; key: StringKey }>("POST", `${base(id)}/keys/${enc(keyId)}/translations/${enc(lang)}/suggest`, undefined, { branch }),
    history: (id: string, keyId: string, lang?: string) =>
      get<{ items: HistoryItem[] }>(`${base(id)}/keys/${enc(keyId)}/history`, { lang }),
    translate: (id: string, body: { branch?: string; langs?: string[]; mode?: "translate" | "tm_only"; key_ids?: string[] }) =>
      send<StringBatch>("POST", `${base(id)}/translate`, body),
    batch: (id: string, batchId: string) => get<StringBatch>(`${base(id)}/batches/${enc(batchId)}`),
    batches: (id: string) => get<ListResponse<StringBatch>>(`${base(id)}/batches`, { limit: 5 }),
    bulk: (
      id: string,
      body: { action: string; branch?: string; key_ids?: string[]; langs?: string[]; tag?: string },
    ) => send<{ action: string; changed?: number; batch?: StringBatch }>("POST", `${base(id)}/bulk`, body),
    branches: (id: string) => get<{ items: StringBranch[] }>(`${base(id)}/branches`),
    createBranch: (id: string, name: string) => send<StringBranch>("POST", `${base(id)}/branches`, { name }),
    deleteBranch: (id: string, branchId: string) => send<null>("DELETE", `${base(id)}/branches/${enc(branchId)}`),
    mergePreview: (id: string, branchId: string) =>
      get<{ branch: StringBranch; conflicts: MergeConflict[] }>(`${base(id)}/branches/${enc(branchId)}/merge-preview`),
    merge: (id: string, branchId: string, resolutions: Record<string, "branch" | "main">) =>
      send<{ applied: number; keys_moved: number }>("POST", `${base(id)}/branches/${enc(branchId)}/merge`, { resolutions }),
    releases: (id: string) => get<ListResponse<StringRelease>>(`${base(id)}/releases`, { limit: 50 }),
    createRelease: (id: string, body: { branch?: string; version_label?: string; formats?: string[]; publish: boolean }) =>
      send<StringRelease>("POST", `${base(id)}/releases`, body, undefined, true),
    publishRelease: (id: string, releaseId: string) => send<StringRelease>("POST", `${base(id)}/releases/${enc(releaseId)}/publish`),
    distributionToken: (id: string) => send<{ token: string }>("POST", `${base(id)}/distribution-token`),
    push: (id: string, file: File, fields: Record<string, string | boolean | undefined>) => {
      const form = new FormData();
      form.set("file", file);
      for (const [k, v] of Object.entries(fields)) if (v !== undefined && v !== "") form.set(k, String(v));
      return tr.request<PushResult>("POST", `${base(id)}/push`, { form });
    },
    pullUrl: (id: string, query: Query) => tr.downloadUrl(`${base(id)}/pull`, query),
    releaseFileUrl: (id: string, releaseId: string, lang: string, fmt: string) =>
      tr.downloadUrl(`${base(id)}/releases/${enc(releaseId)}/files/${enc(lang)}/${enc(fmt)}`),
  };
}

export type StringsApi = ReturnType<typeof createStringsApi>;
export const stringsApi: StringsApi = createStringsApi(proxyTransport);

/** Load every key of a branch (the grid virtualizes them client side). */
export async function loadAllKeys(projectId: string, q: KeyQuery): Promise<StringKey[]> {
  const out: StringKey[] = [];
  let offset: number | null = 0;
  while (offset !== null) {
    const page: { items: StringKey[]; next_offset: number | null } = await stringsApi.keys(projectId, { ...q, offset, limit: 1000 });
    out.push(...page.items);
    offset = page.next_offset;
  }
  return out;
}

// ---------- placeholders (mirror of services/api/arbiter/strings/placeholders.py, simplified)

const PLACEHOLDER_RE =
  /%\{[A-Za-z_][\w.-]*\}|\{\{-?\s*[^{}]+?\s*\}\}|%(?:\d+\$)?[-+0#]*(?:\d+|\*)?(?:\.(?:\d+|\*))?(?:hh|h|ll|l|L|q|z|j|t)?[@diouxXeEfFgGaAcsSp%]|\$\{[^{}]+\}|\{\s*[A-Za-z0-9_]+\s*(?:,\s*(?:number|date|time|spellout|ordinal|duration)\s*(?:,\s*[^{}]*)?)?\}|<\/?[A-Za-z][\w:.-]*(?:\s+[^<>]*?)?\/?>/g;
const ICU_COMPLEX_RE = /\{\s*([A-Za-z0-9_]+)\s*,\s*(plural|selectordinal|select)\s*,/g;

/** Placeholders of a value in order (ICU plural/select arguments as "{arg, kind}"). */
export function extractPlaceholders(value: string): string[] {
  const out: string[] = [];
  for (const m of value.matchAll(ICU_COMPLEX_RE)) out.push(`{${m[1]}, ${m[2]}}`);
  const stripped = value.replace(ICU_COMPLEX_RE, " ");
  for (const m of stripped.matchAll(PLACEHOLDER_RE)) out.push(m[0].replace(/\s+/g, ""));
  return out;
}

/** Multiset difference: what the target misses from the source, and what it adds. */
export function placeholderDiff(source: string, target: string): { missing: string[]; added: string[] } {
  const count = (xs: string[]) => xs.reduce((m, x) => m.set(x, (m.get(x) ?? 0) + 1), new Map<string, number>());
  const s = count(extractPlaceholders(source));
  const t = count(extractPlaceholders(target));
  const missing: string[] = [];
  const added: string[] = [];
  for (const [k, n] of s) for (let i = 0; i < n - (t.get(k) ?? 0); i++) missing.push(k);
  for (const [k, n] of t) for (let i = 0; i < n - (s.get(k) ?? 0); i++) added.push(k);
  return { missing, added };
}

export function valueText(tr: StringTranslation | null | undefined): string {
  if (!tr) return "";
  if (tr.forms) return tr.forms.other ?? Object.values(tr.forms)[0] ?? "";
  return tr.value;
}

export function stateOf(tr: StringTranslation | null | undefined): StringState {
  return tr?.state ?? "untranslated";
}
