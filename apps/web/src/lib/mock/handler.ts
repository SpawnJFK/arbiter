// In-memory mock of the Arbiter v1 API, used when NEXT_PUBLIC_API_MOCK=1.
// It runs on the Next server (route handlers and server components share it via globalThis)
// and returns real `Response` objects so callers cannot tell it apart from the backend.
import type {
  ApiKey,
  Dispute,
  Glossary,
  Job,
  Org,
  Payout,
  Project,
  Quote,
  ReviewerProfile,
  ReviewerTest,
  Role,
  Segment,
  Task,
  Term,
  TermQuestion,
  Tier,
  User,
  Webhook,
  LedgerEntry,
  OrgWithUsage,
  UploadedFile,
} from "../types";
import * as F from "./fixtures";
import { i18nRoute } from "./i18n";
import { agencyRoute, agencyStore, snapshotFor } from "./agency";

interface Store {
  org: Org;
  projects: Project[];
  jobs: Job[];
  segments: Record<string, Segment[]>;
  files: Record<string, UploadedFile & { source_lang: string }>;
  quotes: Record<string, Quote>;
  glossaries: Glossary[];
  terms: Term[];
  termQuestions: TermQuestion[];
  reviewer: ReviewerProfile;
  tests: ReviewerTest[];
  tasks: Task[];
  heldTask: Task | null;
  ledger: LedgerEntry[];
  adminReviewers: ReviewerProfile[];
  disputes: Dispute[];
  payouts: Payout[];
  orgs: OrgWithUsage[];
  apiKeys: ApiKey[];
  webhooks: Webhook[];
  extraUsers: Record<string, User>;
}

function createStore(): Store {
  const now = Date.now();
  const { projects, jobs, segments } = F.makeProjectsAndJobs(now);
  const ag = agencyStore();
  const ifuWf = ag.workflows.find((w) => w.id === "wfl_01JHALDENIFU") ?? null;
  for (const p of projects) p.account_id = p.id === "prj_01JSUPQ4" ? "acc_01JPIXELWAY" : "acc_01JNORDLAB";
  for (const j of jobs) {
    j.account_id = projects.find((p) => p.id === j.project_id)?.account_id ?? null;
    j.workflow = snapshotFor(j.project_id === "prj_01JIFU42" ? ifuWf : null, j.tier);
    j.senate_count = j.state === "delivered" || j.state === "review" ? 6 : 0;
    j.awaiting_client_approval = false;
  }
  projects.unshift({
    id: "prj_01JLEAFLET",
    name: "Patient leaflet PL-7",
    source_lang: "en",
    target_langs: ["sv"],
    tier: "full",
    content_type: "regulatory",
    due_at: F.iso(2 * 86_400_000, now),
    created_at: F.iso(-3 * 86_400_000, now),
    account_id: "acc_01JNORDLAB",
    workflow_template_id: "wfl_01JHALDENIFU",
  });
  jobs.unshift({
    ...jobs[1],
    id: "job_01JLEAFSV",
    project_id: "prj_01JLEAFLET",
    filename: "PL-7_leaflet.docx",
    target_lang: "sv",
    state: "ready",
    tier: "full",
    progress: 1,
    segment_count: 48,
    auto_approved_count: 0,
    review_count: 48,
    delivered_at: null,
    senate_count: 0,
    account_id: "acc_01JNORDLAB",
    workflow: { ...snapshotFor(ifuWf, "full"), client_review_requested_at: F.iso(-2 * 3600_000, now) },
    awaiting_client_approval: true,
    created_at: F.iso(-3 * 86_400_000, now),
  });
  segments.job_01JLEAFSV = F.makeSegments("other", 12).map((x) => ({ ...x, state: "reviewed", decision: "reviewed", origin: "human" }));
  return {
    org: { ...F.ORG },
    projects,
    jobs,
    segments,
    files: {},
    quotes: {},
    glossaries: F.GLOSSARIES.map((g) => ({ ...g })),
    terms: F.TERMS.map((term) => ({ ...term })),
    termQuestions: F.TERM_QUESTIONS.map((q) => ({ ...q })),
    reviewer: structuredClone(F.REVIEWER_PROFILE),
    tests: F.REVIEWER_TESTS.map((reviewer_test) => ({ ...reviewer_test })),
    tasks: F.makeTasks(now),
    heldTask: null,
    ledger: F.makeLedger(now),
    adminReviewers: structuredClone(F.ADMIN_REVIEWERS),
    disputes: F.makeDisputes(now),
    payouts: F.makePayouts(now),
    orgs: structuredClone(F.ADMIN_ORGS),
    apiKeys: F.API_KEYS.map((k) => ({ ...k })),
    webhooks: F.WEBHOOKS.map((w) => ({ ...w })),
    extraUsers: {},
  };
}

const g = globalThis as unknown as { __arbiterMock?: Store };
function store(): Store {
  if (!g.__arbiterMock) g.__arbiterMock = createStore();
  return g.__arbiterMock;
}

// ---- helpers ---------------------------------------------------------------

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status });
}
function noContent(): Response {
  return new Response(null, { status: 204 });
}
function err(status: number, code: string, message: string, details: Record<string, unknown> = {}): Response {
  return json({ error: { code, message, details } }, status);
}
function list<T>(items: T[], q: URLSearchParams): Response {
  const offset = Math.max(0, Number(q.get("offset") ?? 0) || 0);
  const limit = Math.min(200, Math.max(1, Number(q.get("limit") ?? 50) || 50));
  const pageItems = items.slice(offset, offset + limit);
  const next = offset + limit < items.length ? offset + limit : null;
  return json({ items: pageItems, next_offset: next });
}
function file(body: string | Uint8Array, contentType: string, filename: string): Response {
  return new Response(body as BodyInit, {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  });
}

function roleFromToken(headers: Headers): Role | null {
  const auth = headers.get("authorization") ?? "";
  const m = /^Bearer mock\.(admin|pm|client|reviewer)\./.exec(auth);
  return (m?.[1] as Role) ?? null;
}

/** Mock login: the role is derived from the email (reviewer@, admin@, client@, anything else is pm). */
export function mockLogin(email: string): { token: string; user: User; org: Org | null } {
  const e = email.toLowerCase();
  const role: Role = e.startsWith("reviewer") ? "reviewer" : e.startsWith("admin") ? "admin" : e.startsWith("client") ? "client" : "pm";
  const s = store();
  const user = s.extraUsers[e] ?? { ...F.USERS[role], email };
  return { token: `mock.${role}.${Math.random().toString(36).slice(2)}`, user, org: user.org_id ? s.org : null };
}

export function mockRegister(body: { org_name: string; name: string; email: string }) {
  const s = store();
  s.org = { ...s.org, name: body.org_name || s.org.name };
  const user: User = { ...F.USERS.pm, name: body.name, email: body.email };
  s.extraUsers[body.email.toLowerCase()] = user;
  return { token: `mock.pm.${Math.random().toString(36).slice(2)}`, user, org: s.org };
}

export function mockApply(body: { name: string; email: string; pairs: { source_lang: string; target_lang: string }[]; domains: string[] }) {
  const s = store();
  const user: User = { ...F.USERS.reviewer, name: body.name, email: body.email };
  s.extraUsers[body.email.toLowerCase()] = { ...user, email: `reviewer+${body.email}` };
  const profile: ReviewerProfile = {
    ...s.reviewer,
    level: "candidate",
    status: "applied",
    score: null,
    pairs: body.pairs.map((p) => ({ ...p, status: "testing", score: null })),
    domains: body.domains,
    balance: "0.00",
  };
  return { token: `mock.reviewer.${Math.random().toString(36).slice(2)}`, user, profile };
}

async function readBody(headers: Headers, body: BodyInit | null): Promise<{ json?: Record<string, unknown>; form?: FormData }> {
  if (body == null) return {};
  const ct = headers.get("content-type") ?? "";
  const res = new Response(body, { headers: { "content-type": ct } });
  if (ct.includes("multipart/form-data")) return { form: await res.formData() };
  const text = await res.text();
  if (!text) return {};
  try {
    return { json: JSON.parse(text) as Record<string, unknown> };
  } catch {
    return {};
  }
}

const PRICE_PER_WORD: Record<Tier, number> = { auto: 0.03, ai_review: 0.06, hybrid: 0.11, full: 0.19 };
const ETA: Record<Tier, number> = { auto: 1, ai_review: 4, hybrid: 30, full: 72 };

function buildQuote(fileRec: Store["files"][string], target_langs: string[], content_type: string, org: Org): Quote {
  const words = fileRec.word_count;
  const regulated = org.regulated;
  const auto = 0.62 + ((words % 17) / 100);
  const tiers = {} as Quote["tiers"];
  for (const tier of ["auto", "ai_review", "hybrid", "full"] as Tier[]) {
    const price = (words * target_langs.length * PRICE_PER_WORD[tier]).toFixed(2);
    const blocked = regulated && (tier === "auto" || tier === "ai_review");
    tiers[tier] = {
      price,
      est_auto_rate: tier === "full" ? 0 : Math.min(0.95, tier === "hybrid" ? auto - 0.06 : auto),
      eta_hours: ETA[tier] + Math.ceil(words / 4000) * (tier === "full" ? 24 : tier === "hybrid" ? 6 : 0),
      available: !blocked,
      blocked_reason: blocked
        ? `Your organisation is set to a regulated vertical (${(org.vertical ?? "regulated").replace(/_/g, " ")}). Machine-only tiers are not offered: every shipped segment needs a human decision.`
        : null,
    };
  }
  const exact = Math.round(words * 0.12);
  const ctx = Math.round(words * 0.05);
  const fuzzy = Math.round(words * 0.18);
  const reps = Math.round(words * 0.07);
  return {
    id: F.newId("quo"),
    file_id: fileRec.id,
    source_lang: fileRec.source_lang,
    target_langs,
    content_type,
    word_count: words,
    currency: "EUR",
    valid_until: F.iso(7 * 24 * 3600_000),
    analysis: { tm_context: ctx, tm_exact: exact, tm_fuzzy: fuzzy, new: words - exact - ctx - fuzzy - reps, repetitions: reps },
    tiers,
  };
}

function xliffFor(job: Job, segs: Segment[]): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const units = segs
    .map(
      (s) =>
        `    <unit id="${s.id}">\n      <segment state="${s.state === "delivered" ? "final" : "translated"}">\n        <source>${esc(s.source_tagged)}</source>\n        <target>${esc(s.target_tagged ?? "")}</target>\n      </segment>\n    </unit>`,
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.1" srcLang="${job.source_lang}" trgLang="${job.target_lang}">\n  <file id="${job.file_id}" original="${esc(job.filename)}">\n${units}\n  </file>\n</xliff>\n`;
}

/** Minimal one-page PDF so the evidence-pack download is a real file in mock mode. */
function tinyPdf(lines: string[]): Uint8Array {
  const esc = (s: string) => s.replace(/[\\()]/g, (c) => `\\${c}`).replace(/[^\x20-\x7e]/g, "?");
  const text = lines.map((l, i) => `BT /F1 ${i === 0 ? 14 : 10} Tf 56 ${780 - i * 18} Td (${esc(l)}) Tj ET`).join("\n");
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objs.forEach((o, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  out += offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(out);
}

function evidenceFor(job: Job, segs: Segment[]) {
  return {
    job_id: job.id,
    generated_at: new Date().toISOString(),
    tier: job.tier,
    threshold: job.threshold,
    no_reviewer_policy_applied: null,
    summary: {
      segments: job.segment_count,
      auto_approved: job.auto_approved_count,
      ai_reviewed: job.ai_reviewed_count,
      human_reviewed: job.review_count,
    },
    segments: segs.map((s) => ({
      id: s.id,
      seq: s.seq,
      decision: s.decision,
      qe_score: s.qe_score,
      reasons: s.reasons,
      engine: s.engine,
      reviewer_id: s.reviewer_id,
      is_control_sample: s.is_control_sample,
    })),
  };
}

// ---- router ----------------------------------------------------------------

type Ctx = {
  method: string;
  parts: string[];
  q: URLSearchParams;
  body: Record<string, unknown>;
  form?: FormData;
  role: Role;
  s: Store;
};

export async function mockFetch(method: string, pathWithQuery: string, headers: Headers, rawBody: BodyInit | null): Promise<Response> {
  // Small latency so loading states are visible but the demo stays snappy.
  await new Promise((r) => setTimeout(r, 60));
  const url = new URL(pathWithQuery, "http://mock.local");
  if (url.pathname === "/healthz") return json({ ok: true });
  const role = roleFromToken(headers);
  const parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
  // UI localization reads are public.
  if (parts[0] === "i18n") return i18nRoute(method, parts, role, {}) ?? err(404, "not_found", `No mock for ${method} ${url.pathname}`);
  if (!role) return err(401, "unauthenticated", "Missing or invalid token.");
  const { json: body, form } = await readBody(headers, rawBody);
  if (parts[0] === "admin" && parts[1] === "i18n") return i18nRoute(method, parts, role, body ?? {}) ?? err(404, "not_found", `No mock for ${method} ${url.pathname}`);
  const ctx: Ctx = { method, parts, q: url.searchParams, body: body ?? {}, form, role, s: store() };
  try {
    return (await route(ctx)) ?? err(404, "not_found", `No mock for ${method} ${url.pathname}`);
  } catch (e) {
    return err(500, "mock_error", e instanceof Error ? e.message : "Mock failure");
  }
}

function isCustomer(r: Role) {
  return r === "pm" || r === "client";
}

async function route(c: Ctx): Promise<Response | null> {
  const { method: m, parts: p, s } = c;
  const [a, b, cc, d, e] = p;

  // --- account
  if (a === "me" && m === "GET") {
    const user = F.USERS[c.role];
    return json({ user, org: isCustomer(c.role) ? s.org : null });
  }
  if (a === "org") {
    if (!isCustomer(c.role)) return err(403, "forbidden", "Org settings are for customer users.");
    if (m === "GET") return json(s.org);
    if (m === "PATCH") {
      if (c.role !== "pm") return err(403, "forbidden", "Only PMs can change org policies.");
      s.org = { ...s.org, ...(c.body as Partial<Org>) };
      return json(s.org);
    }
  }
  if (a === "api-keys") {
    if (!b && m === "GET") return list(s.apiKeys, c.q);
    if (!b && m === "POST") {
      const id = F.newId("key");
      const prefix = `ak_${Math.random().toString(36).slice(2, 6)}`;
      const key: ApiKey = {
        id,
        name: String(c.body.name ?? "Untitled"),
        prefix,
        scopes: (c.body.scopes as string[]) ?? [],
        created_at: new Date().toISOString(),
        last_used_at: null,
      };
      s.apiKeys.unshift(key);
      return json({ id, name: key.name, prefix, key: `${prefix}.${crypto.randomUUID().replace(/-/g, "")}` }, 201);
    }
    if (b && m === "DELETE") {
      s.apiKeys = s.apiKeys.filter((k) => k.id !== b);
      return noContent();
    }
  }

  // --- files / quotes / projects / jobs
  if (a === "files" && m === "POST") {
    const value = c.form?.get("file");
    const name = value && typeof value === "object" && "name" in value ? (value as File).name : "upload.docx";
    const size = value && typeof value === "object" && "size" in value ? (value as File).size : 40_000;
    const words = Math.max(180, Math.min(48_000, Math.round(size / 6.1)));
    const ext = name.split(".").pop()?.toLowerCase() ?? "docx";
    const rec = {
      id: F.newId("fil"),
      filename: name,
      format: ext,
      segment_count: Math.round(words / 13),
      word_count: words,
      warnings: ext === "pdf" ? ["PDF input: layout is not preserved; delivery is DOCX."] : [],
      source_lang: String(c.form?.get("source_lang") ?? "en"),
    };
    s.files[rec.id] = rec;
    const { source_lang: _sl, ...out } = rec;
    void _sl;
    return json(out, 201);
  }
  if (a === "quotes") {
    if (!b && m === "POST") {
      const value = s.files[String(c.body.file_id)];
      if (!value) return err(404, "not_found", "File not found.");
      const qt = buildQuote(value, (c.body.target_langs as string[]) ?? [], String(c.body.content_type ?? "general"), s.org);
      s.quotes[qt.id] = qt;
      return json(qt, 201);
    }
    if (b && m === "GET") return s.quotes[b] ? json(s.quotes[b]) : err(404, "not_found", "Quote not found.");
  }
  if (a === "projects") {
    if (!b && m === "GET") return list([...s.projects].sort((x, y) => y.created_at.localeCompare(x.created_at)), c.q);
    if (!b && m === "POST") {
      const qt = s.quotes[String(c.body.quote_id)];
      if (!qt) return err(404, "not_found", "Quote not found or expired.");
      const ag = agencyStore();
      const acc = c.body.account_id ? ag.accounts.find((a) => a.id === c.body.account_id) : undefined;
      const wfId = (c.body.workflow_template_id as string | undefined) ?? (c.body.tier ? undefined : acc?.workflow_template_id ?? undefined);
      const wfT = wfId ? ag.workflows.find((w) => w.id === wfId) ?? null : null;
      const tier = (wfT?.tier ?? (c.body.tier as Tier | undefined) ?? acc?.default_tier ?? s.org.default_tier) as Tier;
      if (!qt.tiers[tier]?.available) return err(422, "tier_blocked", qt.tiers[tier]?.blocked_reason ?? "Tier not available.");
      const value = s.files[qt.file_id];
      const project: Project = {
        id: F.newId("prj"),
        name: String(c.body.name ?? value.filename),
        source_lang: qt.source_lang,
        target_langs: qt.target_langs,
        tier,
        content_type: qt.content_type,
        due_at: (c.body.due_at as string) ?? null,
        created_at: new Date().toISOString(),
        account_id: acc?.id ?? null,
        workflow_template_id: wfT?.id ?? null,
      };
      s.projects.unshift(project);
      const perLang = Number(qt.tiers[tier].price) / Math.max(1, qt.target_langs.length);
      for (const lang of qt.target_langs) {
        const job: Job = {
          id: F.newId("job"),
          project_id: project.id,
          file_id: value.id,
          filename: value.filename,
          source_lang: qt.source_lang,
          target_lang: lang,
          tier,
          content_type: qt.content_type,
          state: "running",
          segment_count: value.segment_count,
          word_count: value.word_count,
          auto_approved_count: 0,
          review_count: 0,
          ai_reviewed_count: 0,
          progress: 0,
          threshold: 78,
          revenue: perLang.toFixed(2),
          cost: (perLang * 0.42).toFixed(2),
          margin: (perLang * 0.58).toFixed(2),
          failure_reason: null,
          due_at: project.due_at,
          delivered_at: null,
          created_at: project.created_at,
          account_id: acc?.id ?? null,
          workflow: snapshotFor(wfT, tier),
          senate_count: 0,
          awaiting_client_approval: false,
        };
        s.jobs.unshift(job);
        s.segments[job.id] = [];
      }
      return json(project, 201);
    }
    if (b && m === "GET") {
      const pr = s.projects.find((x) => x.id === b);
      if (!pr) return err(404, "not_found", "Project not found.");
      return json({ ...pr, jobs: s.jobs.filter((j) => j.project_id === b) });
    }
  }
  if (a === "jobs") {
    if (!b && m === "GET") {
      const state = c.q.get("state");
      const pid = c.q.get("project_id");
      return list(s.jobs.filter((j) => (!state || j.state === state) && (!pid || j.project_id === pid)), c.q);
    }
    const job = s.jobs.find((j) => j.id === b);
    if (!job) return err(404, "not_found", "Job not found.");
    const segs = s.segments[job.id] ?? [];
    const hideMoney = (j: Job): Job => (c.role === "client" ? { ...j, revenue: null, cost: null, margin: null } : j);
    if (!cc && m === "GET") return json(hideMoney(job));
    if (cc === "segments" && !d && m === "GET") {
      const st = c.q.get("state");
      const dec = c.q.get("decision");
      return list(segs.filter((x) => (!st || x.state === st) && (!dec || x.decision === dec)), c.q);
    }
    if (cc === "segments" && d) {
      const seg = segs.find((x) => x.id === d);
      if (!seg) return err(404, "not_found", "Segment not found.");
      if (!e && m === "PATCH") {
        const target = String(c.body.target_tagged ?? "");
        const tagsOf = (x: string) => (x.match(/⟦\/?\d+\/?⟧/g) ?? []).sort().join(",");
        if (tagsOf(target) !== tagsOf(seg.source_tagged))
          return err(422, "tag_mismatch", "Target tags must match the source tags.", { expected: tagsOf(seg.source_tagged) });
        seg.target_tagged = target;
        seg.origin = "human";
        seg.state = job.state === "delivered" ? "delivered" : "reviewed";
        seg.reasons = [...seg.reasons.filter((r) => !r.startsWith("Edited by")), "Edited by customer (counts as human review)"];
        return json(seg);
      }
      if (e === "approve" && m === "POST") {
        if (seg.state === "needs_review") seg.state = "reviewed";
        return json(seg);
      }
    }
    if (cc === "client-approve" && m === "POST") {
      if (!job.awaiting_client_approval) return err(409, "not_awaiting_client", "This job is not waiting for client approval.");
      job.awaiting_client_approval = false;
      job.client_approved_at = new Date().toISOString();
      job.state = "delivered";
      job.delivered_at = new Date().toISOString();
      for (const x of segs) x.state = "delivered";
      return json(hideMoney(job));
    }
    if (cc === "cancel" && m === "POST") {
      if (["delivered", "cancelled", "failed"].includes(job.state)) return err(409, "invalid_state", `Job is ${job.state}.`);
      job.state = "cancelled";
      return json(hideMoney(job));
    }
    if (cc === "download" && m === "GET") {
      if (job.state !== "delivered") return err(409, "not_delivered", "The translated file is available once the job is delivered.");
      const text = segs.map((x) => (x.target_tagged ?? "").replace(/⟦\/?\d+\/?⟧/g, "")).join("\n");
      const base = job.filename.replace(/\.[^.]+$/, "");
      return file(text || "(empty)", "text/plain; charset=utf-8", `${base}.${job.target_lang}.txt`);
    }
    if (cc === "xliff" && m === "GET") return file(xliffFor(job, segs), "application/xliff+xml", `${job.id}.${job.target_lang}.xlf`);
    if (cc === "evidence" && m === "GET") {
      const ev = evidenceFor(job, segs);
      if (c.q.get("format") === "pdf") {
        return file(
          tinyPdf([
            `Arbiter evidence pack: ${job.id}`,
            `Tier ${job.tier}, threshold ${job.threshold}`,
            `Segments ${job.segment_count}: auto ${job.auto_approved_count}, AI reviewed ${job.ai_reviewed_count}, human ${job.review_count}`,
            "Mock mode: generated from fixtures.",
          ]),
          "application/pdf",
          `${job.id}-evidence.pdf`,
        );
      }
      return file(JSON.stringify(ev, null, 2), "application/json", `${job.id}-evidence.json`);
    }
    if (cc === "report-error" && m === "POST") return json({ id: F.newId("esc") }, 201);
  }
  if (a === "exceptions" && m === "GET") {
    const waiting = s.jobs
      .filter((j) => j.awaiting_client_approval)
      .map((j) => ({ kind: "client_review", job_id: j.id, segment_id: null, reason: "Waiting for the client's approval before delivery", created_at: j.workflow?.client_review_requested_at ?? j.created_at }));
    return list([...waiting, ...F.EXCEPTIONS], c.q);
  }

  // --- linguistic assets
  if (a === "glossaries") {
    if (!b && m === "GET") return list(s.glossaries, c.q);
    if (!b && m === "POST") {
      const gl: Glossary = { id: F.newId("gls"), name: String(c.body.name), content_type: (c.body.content_type as string) || null, version: 1, term_count: 0 };
      s.glossaries.push(gl);
      return json(gl, 201);
    }
    const gl = s.glossaries.find((x) => x.id === b);
    if (!gl) return err(404, "not_found", "Glossary not found.");
    if (cc === "terms" && m === "GET") {
      const q = (c.q.get("q") ?? "").toLowerCase();
      const sl = c.q.get("source_lang");
      const tl = c.q.get("target_lang");
      return list(
        s.terms.filter(
          (term) =>
            term.glossary_id === gl.id &&
            !term.valid_to &&
            (!q || term.source_term.toLowerCase().includes(q) || (term.target_term ?? "").toLowerCase().includes(q)) &&
            (!sl || term.source_lang === sl) &&
            (!tl || term.target_lang === tl),
        ),
        c.q,
      );
    }
    if (cc === "terms" && m === "POST") {
      const toneClass: Term = {
        id: F.newId("trm"),
        glossary_id: gl.id,
        source_lang: String(c.body.source_lang),
        target_lang: String(c.body.target_lang),
        source_term: String(c.body.source_term),
        target_term: (c.body.target_term as string) || null,
        kind: c.body.kind as Term["kind"],
        case_sensitive: Boolean(c.body.case_sensitive),
        note: (c.body.note as string) || null,
        valid_from: new Date().toISOString(),
        valid_to: null,
      };
      s.terms.push(toneClass);
      gl.term_count += 1;
      gl.version += 1;
      return json(toneClass, 201);
    }
    if (cc === "import" && m === "POST") {
      gl.version += 1;
      return json({ imported: 42, skipped: 3, errors: ["Row 17: unknown kind 'required'", "Row 31: empty source term"] });
    }
    if (cc === "export" && m === "GET") {
      const fmt = c.q.get("format") === "tbx" ? "tbx" : "csv";
      const rows = s.terms.filter((term) => term.glossary_id === gl.id && !term.valid_to);
      if (fmt === "csv") {
        const csv = ["source_lang,target_lang,source_term,target_term,kind,case_sensitive,note"]
          .concat(rows.map((row) => [row.source_lang, row.target_lang, row.source_term, row.target_term ?? "", row.kind, row.case_sensitive, row.note ?? ""].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")))
          .join("\n");
        return file(csv, "text/csv", `${gl.name}.csv`);
      }
      const tbx = `<?xml version="1.0"?>\n<tbx type="TBX-Basic" style="dca" xml:lang="en"><text><body>\n${rows
        .map((row) => `<conceptEntry id="${row.id}"><langSec xml:lang="${row.source_lang}"><termSec><term>${row.source_term}</term></termSec></langSec></conceptEntry>`)
        .join("\n")}\n</body></text></tbx>\n`;
      return file(tbx, "application/x-tbx+xml", `${gl.name}.tbx`);
    }
  }
  if (a === "terms" && b) {
    const item = s.terms.find((x) => x.id === b);
    if (!item) return err(404, "not_found", "Term not found.");
    const gl = s.glossaries.find((x) => x.id === item.glossary_id);
    if (m === "PATCH") {
      Object.assign(item, c.body);
      if (gl) gl.version += 1;
      return json(item);
    }
    if (m === "DELETE") {
      item.valid_to = new Date().toISOString();
      if (gl) {
        gl.version += 1;
        gl.term_count = Math.max(0, gl.term_count - 1);
      }
      return noContent();
    }
  }
  if (a === "tm") {
    if (b === "import" && m === "POST") {
      if (c.form?.get("rights_confirmed") !== "true") return err(422, "rights_not_confirmed", "You must confirm you own the rights to this TM.");
      return json({ imported: 1284, skipped: 17 });
    }
    if (b === "search" && m === "GET") {
      const q = (c.q.get("q") ?? "").toLowerCase();
      return list(q ? F.TM_ENTRIES.filter((x) => (x.source_tagged + x.target_tagged).toLowerCase().includes(q.split(" ")[0])) : F.TM_ENTRIES, c.q);
    }
    if (b === "export" && m === "GET") {
      const tmx = `<?xml version="1.0"?>\n<tmx version="1.4"><header srclang="en" datatype="plaintext" segtype="sentence" adminlang="en" o-tmf="arbiter" creationtool="arbiter" creationtoolversion="1"/><body>\n${F.TM_ENTRIES.map((x) => `<tu tuid="${x.entry_id}"><tuv xml:lang="en"><seg>${x.source_tagged}</seg></tuv><tuv xml:lang="de"><seg>${x.target_tagged}</seg></tuv></tu>`).join("\n")}\n</body></tmx>\n`;
      return file(tmx, "application/x-tmx+xml", "arbiter-tm.tmx");
    }
  }
  if (a === "term-questions") {
    if (!b && m === "GET") return list(s.termQuestions, c.q);
    if (b && cc === "answer" && m === "POST") {
      const tq = s.termQuestions.find((x) => x.id === b);
      if (!tq) return err(404, "not_found", "Question not found.");
      tq.status = "answered";
      const gid = c.body.add_to_glossary_id as string | undefined;
      if (gid) {
        s.terms.push({
          id: F.newId("trm"),
          glossary_id: gid,
          source_lang: tq.source_lang,
          target_lang: tq.target_lang,
          source_term: tq.source_term,
          target_term: String(c.body.answer),
          kind: "mandatory",
          case_sensitive: false,
          note: "Added from term question",
          valid_from: new Date().toISOString(),
          valid_to: null,
        });
        const gl = s.glossaries.find((x) => x.id === gid);
        if (gl) {
          gl.term_count += 1;
          gl.version += 1;
        }
      }
      return json(tq);
    }
  }

  // --- quality
  if (a === "quality") {
    if (b === "dashboard") return json({ window_days: 30, segments: 1840, auto_approved: 1259, auto_rate: 0.684, escaped_errors: 4, escaped_rate: 0.0032, control_samples: { total: 26, pending: 3, ok: 21, escaped: 2 }, thresholds: F.THRESHOLDS, engines: F.ENGINES });
    if (b === "thresholds") return list(F.THRESHOLDS, c.q);
  }

  // --- reviewer
  if (a === "reviewer") {
    if (c.role !== "reviewer") return err(403, "forbidden", "Reviewer only.");
    if (b === "me" && m === "GET") return json(s.reviewer);
    if (b === "me" && m === "PATCH") {
      const required = ["legal_name", "tax_id", "address", "date_of_birth", "payout_method"];
      s.reviewer.tax_info_complete = required.every((k) => Boolean(c.body[k]));
      return json(s.reviewer);
    }
    if (b === "tests" && !cc && m === "GET") return list(s.tests, c.q);
    if (b === "tests" && cc && d === "start" && m === "POST") {
      const test = s.tests.find((x) => x.id === cc);
      if (!test) return err(404, "not_found", "Test not found.");
      if (test.status !== "available") return err(409, "not_available", `Test is ${test.status}.`);
      return json({
        attempt_id: `att_${cc}`,
        items: F.TEST_ITEMS.map((it, index) => ({ index, ...it })),
        time_limit_min: test.time_limit_min,
      });
    }
    if (b === "attempts" && cc && d === "submit" && m === "POST") {
      const answers = (c.body.answers as { errors?: unknown[] }[]) ?? [];
      const annotated = answers.reduce((n, x) => n + (x.errors?.length ?? 0), 0);
      const score = Math.min(1, 0.62 + annotated * 0.09);
      const passed = score >= 0.8;
      const test = s.tests.find((x) => `att_${x.id}` === cc);
      if (test) test.status = passed ? "passed" : "failed";
      return json({ score: Number(score.toFixed(2)), passed });
    }
    if (b === "tasks" && cc === "next" && m === "POST") {
      if (s.heldTask) return json(s.heldTask);
      const next = s.tasks.shift();
      if (!next) return noContent();
      next.hold_expires_at = F.iso(10 * 60_000);
      s.heldTask = next;
      return json(next);
    }
    if (b === "tasks" && cc && d === "submit" && m === "POST") {
      const decision = String(c.body.decision);
      const pay = decision === "skip" ? "0.00" : s.heldTask?.pay_estimate ?? "0.30";
      if (decision !== "skip") {
        s.ledger.unshift({ id: F.newId("led"), kind: "task_pay", amount: pay, created_at: new Date().toISOString(), ref: cc });
      }
      s.heldTask = null;
      return json({ ok: true, pay_amount: pay });
    }
    if (b === "tasks" && cc && d === "release" && m === "POST") {
      if (s.heldTask) s.tasks.push(s.heldTask);
      s.heldTask = null;
      return noContent();
    }
    if (b === "earnings" && m === "GET") {
      const sum = (value: (x: LedgerEntry) => boolean) => s.ledger.filter(value).reduce((n, x) => n + Number(x.amount), 0).toFixed(2);
      return json({
        currency: "EUR",
        balance: sum((x) => x.kind !== "payout"),
        pending: "0.00",
        paid: (-Number(sum((x) => x.kind === "payout"))).toFixed(2),
        payout_threshold: s.reviewer.payout_threshold,
        entries: s.ledger,
      });
    }
    if (b === "disputes" && m === "POST") return json({ id: F.newId("dsp"), due_at: F.iso(5 * 24 * 3600_000) }, 201);
  }

  // --- admin
  if (a === "admin") {
    if (c.role !== "admin") return err(403, "forbidden", "Admin only.");
    if (b === "reviewers" && !cc && m === "GET") {
      const st = c.q.get("status");
      return list(s.adminReviewers.filter((r) => !st || r.status === st), c.q);
    }
    if (b === "reviewers" && cc && d === "status" && m === "POST") {
      const r = s.adminReviewers.find((x) => x.id === cc);
      if (!r) return err(404, "not_found", "Reviewer not found.");
      r.status = String(c.body.status);
      if (c.body.level !== undefined) r.level = String(c.body.level);
      return json(r);
    }
    if (b === "disputes" && !cc && m === "GET") return list(s.disputes, c.q);
    if (b === "disputes" && cc && d === "decide" && m === "POST") {
      const dp = s.disputes.find((x) => x.id === cc);
      if (!dp) return err(404, "not_found", "Dispute not found.");
      dp.status = String(c.body.outcome);
      dp.decision_note = String(c.body.note ?? "");
      return json(dp);
    }
    if (b === "payouts" && !cc && m === "GET") return list(s.payouts, c.q);
    if (b === "payouts" && cc === "run" && m === "POST") {
      const eligible = s.adminReviewers.filter((r) => r.tax_info_complete && Number(r.balance) >= Number(r.payout_threshold));
      let total = 0;
      for (const r of eligible) {
        s.payouts.unshift({ id: F.newId("pay"), reviewer_id: r.id, amount: r.balance, state: "pending", created_at: new Date().toISOString() });
        total += Number(r.balance);
        r.balance = "0.00";
      }
      return json({ created: eligible.length, total: total.toFixed(2) });
    }
    if (b === "orgs" && m === "GET") return list(s.orgs, c.q);
  }

  // --- integrations and billing
  if (a === "webhooks") {
    if (!b && m === "GET") return list(s.webhooks.map(({ secret: _s, ...w }) => (void _s, w)), c.q);
    if (!b && m === "POST") {
      const w: Webhook = { id: F.newId("whk"), url: String(c.body.url), events: (c.body.events as Webhook["events"]) ?? [], active: true };
      s.webhooks.push(w);
      return json({ ...w, secret: `whsec_${crypto.randomUUID().replace(/-/g, "")}` }, 201);
    }
    if (b && m === "DELETE") {
      s.webhooks = s.webhooks.filter((w) => w.id !== b);
      return noContent();
    }
  }
  if (a === "usage" && m === "GET") {
    const period = c.q.get("period") ?? new Date().toISOString().slice(0, 7);
    const seed = Number(period.replace("-", "")) % 97;
    return json({ period, words: 12000 + seed * 130, ai_units: String(36000 + seed * 390), review_decisions: 150 + seed, amount: (980 + seed * 11.3).toFixed(2) });
  }
  if (a === "invoices" && m === "GET") return list(F.INVOICES, c.q);

  return agencyRoute({ method: m, parts: p, q: c.q, body: c.body, role: c.role, org: s.org, jobs: s.jobs, projects: s.projects });
}
