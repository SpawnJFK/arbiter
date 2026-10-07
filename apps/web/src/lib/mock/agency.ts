// Agency OS part of the mock API: CRM, price lists, workflows, dashboards, assistant.
// Shapes follow services/api/arbiter/agency/*.py. Fixture data is fictional.
import type {
  Account,
  Activity,
  AssistantMessage,
  AssistantThread,
  Contact,
  Dashboard,
  Deal,
  DealStage,
  Job,
  Org,
  PlanAction,
  PriceList,
  Project,
  Tier,
  Widget,
  Workflow,
  WorkflowStep,
} from "../types";
import { DEAL_STAGES } from "../types";
import { validateWorkflow } from "../workflow";
import { iso, newId } from "./fixtures";

const DAY = 86_400_000;

export interface AgencyStore {
  accounts: Account[];
  contacts: Contact[];
  deals: Deal[];
  activities: Activity[];
  priceLists: PriceList[];
  workflows: Workflow[];
  dashboards: Dashboard[];
  threads: AssistantThread[];
  messages: AssistantMessage[];
}

export interface AgencyCtx {
  method: string;
  parts: string[];
  q: URLSearchParams;
  body: Record<string, unknown>;
  role: string;
  org: Org;
  jobs: Job[];
  projects: Project[];
}

const s = (kind: WorkflowStep["kind"], params: WorkflowStep["params"] = {}): WorkflowStep => ({ kind, params });

const PRESETS: [string, string, string, Tier, WorkflowStep[]][] = [
  ["machine_only", "Machine only", "TM, machine translation and QE; segments ship automatically when the score allows.", "auto", [s("tm"), s("mt"), s("qe"), s("delivery")]],
  ["ai_reviewed", "AI reviewed", "TM, MT and QE; uncertain segments go to the senate and the AI editor, no human.", "ai_review", [s("tm"), s("mt"), s("qe"), s("ai_review"), s("delivery")]],
  ["hybrid", "Hybrid (MT+QE+human for low scores)", "TM, MT and QE; high scores ship, the band goes to the senate, low scores to a human.", "hybrid", [s("tm"), s("mt"), s("qe"), s("senate"), s("human_review"), s("delivery")]],
  ["full_review", "Full human review", "TM, MT and QE as guidance; a human reviews every segment.", "full", [s("tm"), s("mt"), s("qe"), s("human_review"), s("delivery")]],
  [
    "regulated",
    "Regulated: two reviewers + client approval",
    "Every segment reviewed by a senior human, then a second senior reviewer; the client approves before delivery.",
    "full",
    [s("tm"), s("mt"), s("qe"), s("human_review", { min_level: "senior" }), s("second_review"), s("client_review"), s("delivery")],
  ],
];

export const TIER_STEPS: Record<Tier, WorkflowStep[]> = {
  auto: [s("tm"), s("mt"), s("qe"), s("senate"), s("delivery")],
  ai_review: [s("tm"), s("mt"), s("qe"), s("ai_review"), s("delivery")],
  hybrid: [s("tm"), s("mt"), s("qe"), s("senate"), s("human_review"), s("delivery")],
  full: [s("tm"), s("mt"), s("qe"), s("human_review"), s("delivery")],
};

export const DEFAULT_WIDGETS: [Widget["type"], string, Widget["size"]][] = [
  ["kpi", "revenue", "s"],
  ["kpi", "margin_pct", "s"],
  ["kpi", "jobs_active", "s"],
  ["kpi", "jobs_overdue", "s"],
  ["kpi", "auto_rate", "s"],
  ["kpi", "open_deals_value", "s"],
  ["line", "revenue_by_month", "l"],
  ["bar", "jobs_by_state", "m"],
  ["pipeline", "deals_by_stage", "m"],
  ["table", "overdue_jobs", "l"],
  ["table", "open_activities", "m"],
];

export const METRIC_TITLES: Record<string, string> = {
  revenue: "Revenue",
  margin: "Margin",
  margin_pct: "Margin %",
  jobs_active: "Active jobs",
  jobs_overdue: "Overdue jobs",
  auto_rate: "Auto-approval rate",
  escaped_rate: "Escaped error rate",
  open_deals_value: "Open deals",
  words_delivered: "Words delivered",
  reviewer_cost: "Reviewer cost",
  revenue_by_month: "Revenue by month",
  jobs_by_state: "Jobs by state",
  revenue_by_account: "Revenue by account",
  words_by_pair: "Words by language pair",
  auto_rate_by_month: "Auto-approval rate by month",
  deals_by_stage: "Deal pipeline",
  overdue_jobs: "Overdue jobs",
  top_accounts: "Top accounts",
  open_activities: "Open activities",
  recent_deliveries: "Recent deliveries",
};

function wf(id: string, preset: string | null, name: string, description: string, tier: Tier, steps: WorkflowStep[], isDefault = false): Workflow {
  return { id, name, description, content_type: null, tier, steps, is_default: isDefault, preset, archived: false, available: true, blocked_reason: null, created_at: iso(-30 * DAY), updated_at: iso(-30 * DAY) };
}

function widgets(spec: [Widget["type"], string, Widget["size"]][]): Widget[] {
  return spec.map(([type, metric, size], i) => ({ id: `w${i + 1}`, type, metric, size, title: METRIC_TITLES[metric] ?? metric }));
}

function createStore(): AgencyStore {
  const now = Date.now();
  const acc = (id: string, name: string, kind: Account["kind"], industry: string, country: string, extra: Partial<Account> = {}): Account => ({
    id, name, kind, status: "active", industry, country, vat_id: null, currency: "EUR", default_tier: null, workflow_template_id: null, price_list_id: null, owner_user_id: "usr_01JPM", notes: null, created_at: iso(-60 * DAY, now), ...extra,
  });
  const workflows = [
    ...PRESETS.map(([key, name, desc, tier, steps]) => wf(`wfl_01J${key.toUpperCase().replace(/_/g, "")}`, key, name, desc, tier, steps)),
    wf("wfl_01JHALDENIFU", null, "Halden IFU (senior review + client sign-off)", "For instructions for use: senior reviewer, then client approval.", "full", [s("tm"), s("mt"), s("qe", { threshold: 82 }), s("human_review", { min_level: "senior" }), s("client_review"), s("delivery")], true),
  ];
  const priceLists: PriceList[] = [
    {
      id: "prl_01JSTANDARD",
      name: "Standard 2026",
      currency: "EUR",
      rates: [
        { tier: "auto", per_word: "0.03" },
        { tier: "ai_review", per_word: "0.06" },
        { tier: "hybrid", per_word: "0.11" },
        { tier: "full", per_word: "0.19" },
        { source_lang: "en", target_lang: "ja", tier: "full", per_word: "0.24" },
      ],
      tm_weights: { context: "0", exact: "0.1", fuzzy_95: "0.3", fuzzy_85: "0.6", fuzzy_75: "0.8", new: "1", repetition: "0.1" },
      minimum_charge: "25.00",
      archived: false,
      created_at: iso(-90 * DAY, now),
      updated_at: iso(-10 * DAY, now),
    },
    {
      id: "prl_01JMEDTECH",
      name: "Medtech clients",
      currency: "EUR",
      rates: [
        { tier: "hybrid", per_word: "0.13" },
        { tier: "full", per_word: "0.21" },
      ],
      tm_weights: null,
      minimum_charge: "60.00",
      archived: false,
      created_at: iso(-40 * DAY, now),
      updated_at: iso(-40 * DAY, now),
    },
  ];
  const accounts = [
    acc("acc_01JNORDLAB", "Nordlab Diagnostics", "client", "Medical devices", "SE", { default_tier: "full", workflow_template_id: "wfl_01JHALDENIFU", price_list_id: "prl_01JMEDTECH", notes: "Prefers delivery as DOCX with tracked changes." }),
    acc("acc_01JPIXELWAY", "Pixelway Games", "client", "Gaming", "PL", { default_tier: "hybrid", price_list_id: "prl_01JSTANDARD" }),
    acc("acc_01JKORSAKOV", "Korsakov & Partners", "prospect", "Legal", "AT"),
    acc("acc_01JBRIGHTPATH", "Brightpath Learning", "client", "E-learning", "IE", { default_tier: "ai_review", price_list_id: "prl_01JSTANDARD" }),
  ];
  const contacts: Contact[] = [
    { id: "con_01JA", account_id: "acc_01JNORDLAB", name: "Ingrid Holm", email: "ingrid.holm@nordlab.example", phone: "+46 8 555 0101", role: "Regulatory affairs", is_primary: true, created_at: iso(-50 * DAY, now) },
    { id: "con_01JB", account_id: "acc_01JNORDLAB", name: "Per Ekström", email: "per.ekstrom@nordlab.example", phone: null, role: "Technical writer", is_primary: false, created_at: iso(-20 * DAY, now) },
    { id: "con_01JC", account_id: "acc_01JPIXELWAY", name: "Kasia Nowak", email: "kasia@pixelway.example", phone: null, role: "Localization lead", is_primary: true, created_at: iso(-30 * DAY, now) },
  ];
  const deal = (id: string, account_id: string, account_name: string, title: string, value: string, stage: DealStage, closeDays: number | null): Deal => ({
    id, account_id, account_name, title, value, currency: "EUR", stage, expected_close: closeDays === null ? null : iso(closeDays * DAY, now).slice(0, 10), quote_id: null, lost_reason: stage === "lost" ? "Chose an in-house team" : null, owner_user_id: "usr_01JPM", created_at: iso(-25 * DAY, now), updated_at: iso(-2 * DAY, now),
  });
  const deals = [
    deal("dea_01JA", "acc_01JNORDLAB", "Nordlab Diagnostics", "IFU set for the P500 analyser (9 languages)", "14800.00", "negotiation", 12),
    deal("dea_01JB", "acc_01JPIXELWAY", "Pixelway Games", "Season 4 UI strings", "3200.00", "proposal", 20),
    deal("dea_01JC", "acc_01JKORSAKOV", "Korsakov & Partners", "Contract templates DE>EN", "5600.00", "qualified", 35),
    deal("dea_01JD", "acc_01JBRIGHTPATH", "Brightpath Learning", "Course catalogue, 6 languages", "2100.00", "won", null),
    deal("dea_01JE", "acc_01JKORSAKOV", "Korsakov & Partners", "Website localisation", "1800.00", "lead", 60),
    deal("dea_01JF", "acc_01JPIXELWAY", "Pixelway Games", "Store listing refresh", "900.00", "lost", null),
  ];
  const act = (id: string, account_id: string, kind: Activity["kind"], body: string, dueDays: number | null, done: boolean, createdDays: number): Activity => ({
    id, account_id, deal_id: null, kind, body, due_at: dueDays === null ? null : iso(dueDays * DAY, now), done, done_at: done ? iso(createdDays * DAY + 3600_000, now) : null, user_id: "usr_01JPM", created_at: iso(createdDays * DAY, now),
  });
  const activities = [
    act("act_01JA", "acc_01JNORDLAB", "task", "Send the revised P500 quote with the medtech price list", 1, false, -1),
    act("act_01JB", "acc_01JNORDLAB", "call", "Kick-off call with Ingrid: 9 languages, EU MDR deadline in March", null, true, -6),
    act("act_01JC", "acc_01JNORDLAB", "note", "They want the second review done by a reviewer with medical device experience.", null, true, -5),
    act("act_01JD", "acc_01JPIXELWAY", "task", "Ask for the Season 4 glossary export", -1, false, -3),
    act("act_01JE", "acc_01JKORSAKOV", "meeting", "Intro meeting in Vienna", 6, false, -2),
  ];
  return {
    accounts,
    contacts,
    deals,
    activities,
    priceLists,
    workflows,
    dashboards: [{ id: "dsh_01JDEFAULT", name: "Overview", widgets: widgets(DEFAULT_WIDGETS), is_default: true, created_at: iso(-30 * DAY, now), updated_at: iso(-30 * DAY, now) }],
    threads: [],
    messages: [],
  };
}

const g = globalThis as unknown as { __arbiterAgency?: AgencyStore };
export function agencyStore(): AgencyStore {
  if (!g.__arbiterAgency) g.__arbiterAgency = createStore();
  return g.__arbiterAgency;
}

// ---- helpers ---------------------------------------------------------------

const json = (data: unknown, status = 200) => Response.json(data, { status });
const err = (status: number, code: string, message: string, details: Record<string, unknown> = {}) => json({ error: { code, message, details } }, status);
function list<T>(items: T[], q: URLSearchParams) {
  const offset = Math.max(0, Number(q.get("offset") ?? 0) || 0);
  const limit = Math.min(200, Math.max(1, Number(q.get("limit") ?? 50) || 50));
  return json({ items: items.slice(offset, offset + limit), next_offset: offset + limit < items.length ? offset + limit : null });
}
const str = (v: unknown) => (v === undefined || v === null ? null : String(v));
const nowIso = () => new Date().toISOString();

export function snapshotFor(w: Workflow | null, tier: Tier) {
  return w
    ? { template_id: w.id, name: w.name, tier: w.tier, source: "template" as const, steps: w.steps.map((x) => ({ ...x })) }
    : { template_id: null, name: `${tier} (tier default)`, tier, source: "tier" as const, steps: TIER_STEPS[tier].map((x) => ({ ...x })) };
}

function accountDetail(st: AgencyStore, a: Account, jobs: Job[], projects: Project[]) {
  const aj = jobs.filter((j) => j.account_id === a.id);
  const delivered = aj.filter((j) => ["delivered", "settled"].includes(j.state));
  const rev = delivered.reduce((n, j) => n + Number(j.revenue ?? 0), 0);
  const cost = delivered.reduce((n, j) => n + Number(j.cost ?? 0), 0);
  return {
    ...a,
    contacts: st.contacts.filter((c) => c.account_id === a.id).sort((x, y) => Number(y.is_primary) - Number(x.is_primary)),
    deals: st.deals.filter((d) => d.account_id === a.id),
    recent_activities: st.activities.filter((x) => x.account_id === a.id).sort((x, y) => y.created_at.localeCompare(x.created_at)).slice(0, 20),
    stats: {
      projects: projects.filter((p) => p.account_id === a.id).length,
      jobs_active: aj.filter((j) => !["delivered", "settled", "cancelled", "failed"].includes(j.state)).length,
      revenue_total: rev.toFixed(2),
      revenue_90d: rev.toFixed(2),
      margin_90d: (rev - cost).toFixed(2),
    },
  };
}

// ---- dashboards data -------------------------------------------------------

function widgetData(st: AgencyStore, c: AgencyCtx, w: Widget, days: number) {
  const jobs = c.jobs;
  const delivered = jobs.filter((j) => ["delivered", "settled"].includes(j.state));
  const rev = delivered.reduce((n, j) => n + Number(j.revenue ?? 0), 0) * (days / 30);
  const cost = delivered.reduce((n, j) => n + Number(j.cost ?? 0), 0) * (days / 30);
  const months = Math.max(1, Math.round(days / 30));
  const monthLabels = Array.from({ length: Math.min(12, months + 1) }, (_, i) => {
    const d = new Date();
    d.setUTCMonth(d.getUTCMonth() - (Math.min(12, months + 1) - 1 - i));
    return d.toISOString().slice(0, 7);
  });
  const overdue = jobs.filter((j) => j.due_at && new Date(j.due_at).getTime() < Date.now() && !["delivered", "settled", "cancelled"].includes(j.state));
  if (w.type === "kpi") {
    switch (w.metric) {
      case "revenue":
        return { value: rev.toFixed(2), unit: "EUR", previous: (rev * 0.86).toFixed(2) };
      case "margin":
        return { value: (rev - cost).toFixed(2), unit: "EUR", previous: ((rev - cost) * 0.9).toFixed(2) };
      case "margin_pct":
        return { value: rev ? Math.round(((rev - cost) / rev) * 10000) / 100 : null, unit: "%", previous: 54.2 };
      case "jobs_active":
        return { value: jobs.filter((j) => !["delivered", "settled", "cancelled", "failed"].includes(j.state)).length, unit: "jobs" };
      case "jobs_overdue":
        return { value: overdue.length + 1, unit: "jobs" };
      case "auto_rate":
        return { value: 0.684, unit: "ratio", previous: 0.651 };
      case "escaped_rate":
        return { value: 0.0032, unit: "ratio", previous: 0.0041 };
      case "open_deals_value": {
        const open = st.deals.filter((d) => !["won", "lost"].includes(d.stage));
        return { value: open.reduce((n, d) => n + Number(d.value), 0).toFixed(2), unit: "EUR", count: open.length };
      }
      case "words_delivered":
        return { value: delivered.reduce((n, j) => n + j.word_count, 0) * Math.round(days / 30), unit: "words" };
      case "reviewer_cost":
        return { value: (cost * 0.6).toFixed(2), unit: "EUR", previous: (cost * 0.5).toFixed(2) };
    }
  }
  if (w.type === "bar" || w.type === "line") {
    switch (w.metric) {
      case "revenue_by_month":
        return { unit: "EUR", points: monthLabels.map((label, i) => ({ label, value: (1400 + ((i * 937) % 1100) + i * 180).toFixed(2) })) };
      case "auto_rate_by_month":
        return { unit: "ratio", points: monthLabels.map((label, i) => ({ label, value: 0.6 + ((i * 7) % 10) / 100 })) };
      case "jobs_by_state": {
        const counts = new Map<string, number>();
        for (const j of jobs) counts.set(j.state, (counts.get(j.state) ?? 0) + 1);
        return { unit: "jobs", points: [...counts].map(([label, value]) => ({ label, value })) };
      }
      case "revenue_by_account":
        return { unit: "EUR", points: st.accounts.filter((a) => a.kind === "client").map((a, i) => ({ label: a.name, id: a.id, value: (3200 - i * 640).toFixed(2) })) };
      case "words_by_pair":
        return { unit: "words", points: [["en-de", 18240], ["en-fr", 9120], ["en-ja", 6120], ["en-pt-BR", 9400], ["en-es", 1840]].map(([label, value]) => ({ label: String(label), value: Number(value) })) };
    }
  }
  if (w.type === "pipeline") {
    return {
      currency: "EUR",
      stages: DEAL_STAGES.map((stage) => {
        const ds = st.deals.filter((d) => d.stage === stage);
        return { stage, count: ds.length, value: ds.reduce((n, d) => n + Number(d.value), 0).toFixed(2) };
      }),
    };
  }
  if (w.type === "table") {
    switch (w.metric) {
      case "overdue_jobs":
        return {
          columns: ["job_id", "project", "account", "target_lang", "state", "due_at", "hours_overdue"],
          rows: [
            { job_id: "job_01JIFUJA", project: "IFU v4.2, infusion pump P300", account: "Nordlab Diagnostics", target_lang: "ja", state: "running", due_at: iso(-0.5 * DAY), hours_overdue: 12 },
            ...overdue.map((j) => ({ job_id: j.id, project: c.projects.find((p) => p.id === j.project_id)?.name ?? "", account: null, target_lang: j.target_lang, state: j.state, due_at: j.due_at, hours_overdue: Math.round((Date.now() - new Date(j.due_at!).getTime()) / 3600_000) })),
          ],
        };
      case "top_accounts":
        return { columns: ["account_id", "name", "revenue", "margin", "jobs"], rows: st.accounts.filter((a) => a.kind === "client").map((a, i) => ({ account_id: a.id, name: a.name, revenue: (3200 - i * 640).toFixed(2), margin: (1900 - i * 380).toFixed(2), jobs: 6 - i })) };
      case "open_activities":
        return {
          columns: ["id", "account", "kind", "body", "due_at", "overdue"],
          rows: st.activities.filter((a) => !a.done).map((a) => ({ id: a.id, account_id: a.account_id, account: st.accounts.find((x) => x.id === a.account_id)?.name, kind: a.kind, body: a.body, due_at: a.due_at, overdue: Boolean(a.due_at && new Date(a.due_at).getTime() < Date.now()) })),
        };
      case "recent_deliveries":
        return { columns: ["job_id", "project", "filename", "target_lang", "words", "delivered_at", "revenue"], rows: delivered.map((j) => ({ job_id: j.id, project: c.projects.find((p) => p.id === j.project_id)?.name, filename: j.filename, target_lang: j.target_lang, words: j.word_count, delivered_at: j.delivered_at, revenue: j.revenue })) };
    }
  }
  return null;
}

// ---- assistant (rule-based planner, mirrors the backend's offline heuristic) ----

function plan(content: string): { reply: string; plan: PlanAction[] | null } {
  const text = content.trim();
  const lower = text.toLowerCase();
  const actions: PlanAction[] = [];
  const sr = /\b(mi smo|naši|nasi|cena|reči|reci|hoću|hocu|revizija)\b/.test(lower);

  const nameMatch = /(?:mi smo agencija|we are|we're)\s+([A-Z][\w&.\- ]{1,40}?)(?:[.,]|\s+(?:and|a|i)\s)/i.exec(text);
  if (nameMatch) actions.push({ type: "update_org", summary: `Rename the organisation to "${nameMatch[1].trim()}"`, data: { name: nameMatch[1].trim() } });

  const clientsMatch = /(?:klijenti su|clients are|our clients:?)\s+(.+?)\.\s+(?=[A-ZŠĐČĆŽ])/i.exec(text);
  const clients = clientsMatch ? clientsMatch[1].split(/,|\s+i\s+|\s+and\s+/).map((x) => x.trim()).filter(Boolean) : [];

  const steps: WorkflowStep[] = [];
  if (/\bmt\b|machine/.test(lower)) steps.push(s("tm"), s("mt"));
  if (/\bqe\b|quality estimation/.test(lower)) steps.push(s("qe"));
  const second = /druga revizija|second review|two reviewers|dva revizora/.test(lower);
  if (/revizija|review/.test(lower)) steps.push(s("human_review"));
  if (second) steps.push(s("second_review"));
  if (/odobrenje klijenta|client approval|client approves|klijent odobr/.test(lower)) steps.push(s("client_review"));
  if (steps.length) {
    if (!steps.some((x) => x.kind === "qe")) steps.splice(steps.findIndex((x) => x.kind === "mt") + 1, 0, s("qe"));
    steps.push(s("delivery"));
    const pharma = /farmacij|pharma/.test(lower);
    const name = second ? (pharma ? "Pharma: MT + QE + two reviews + client approval" : "MT + QE + two reviews + client approval") : "MT + QE + review";
    actions.push({ type: "create_workflow", summary: `Create workflow "${name}" (${steps.map((x) => x.kind).join(" → ")})`, data: { name, tier: "full", steps, content_type: pharma ? "regulatory" : null } });
  }

  const price = /(\d+[.,]\d+)\s*(?:eur|€)\s*(?:po reči|po reci|per word|\/word)/i.exec(text);
  if (price) {
    const pw = price[1].replace(",", ".");
    actions.push({ type: "create_price_list", summary: `Create price list "Standard" at ${pw} EUR per word (all tiers)`, data: { name: "Standard", currency: "EUR", rates: (["auto", "ai_review", "hybrid", "full"] as Tier[]).map((tier) => ({ tier, per_word: pw })) } });
  }
  for (const c of clients) {
    actions.push({ type: "create_account", summary: `Create client account "${c}"${/pharma/i.test(c) ? " with the pharma workflow" : ""}`, data: { name: c, kind: "client", ...(price ? { price_list: "Standard" } : {}), ...(/pharma/i.test(c) && steps.length ? { workflow: actions.find((a) => a.type === "create_workflow")?.data.name } : {}) } });
  }
  const metrics: string[] = [];
  if (/prihod|revenue/.test(lower)) metrics.push("revenue", "revenue_by_month");
  if (/marž|marz|margin/.test(lower)) metrics.push("margin", "margin_pct");
  if (/kasn|overdue|late/.test(lower)) metrics.push("jobs_overdue", "overdue_jobs");
  if (metrics.length) {
    const ws = metrics.map((m) => ({ type: m.endsWith("_month") ? "line" : m === "overdue_jobs" ? "table" : "kpi", metric: m, size: m.endsWith("_month") || m === "overdue_jobs" ? "l" : "s" }));
    actions.push({ type: "create_dashboard", summary: `Create dashboard "Management" with ${ws.length} widgets (${metrics.join(", ")})`, data: { name: "Management", widgets: ws } });
  }

  if (actions.length === 0) {
    return {
      reply: sr
        ? "Mogu da odgovorim na pitanja o poslovima, prihodu i ponudama, ili da predložim podešavanje radnog prostora. Opišite agenciju, klijente, tok rada i cene."
        : "I can answer questions about your jobs, revenue and deals, or propose a workspace setup. Describe your agency, clients, workflow and prices and I will draft a plan.",
      plan: null,
    };
  }
  return {
    reply: sr
      ? `Predlažem ${actions.length} izmena. Ništa nije promenjeno dok ne primenite plan: označite stavke koje želite i kliknite "Apply".`
      : `Here is a plan with ${actions.length} actions. Nothing changes until you apply it: tick what you want and click Apply.`,
    plan: actions,
  };
}

function applyAction(st: AgencyStore, c: AgencyCtx, a: PlanAction, results: AssistantMessage["results"]): { id: string } {
  const d = a.data as Record<string, unknown>;
  const byName = <T extends { name: string; id: string }>(xs: T[], n: unknown) => xs.find((x) => x.name.toLowerCase() === String(n ?? "").toLowerCase());
  void results;
  switch (a.type) {
    case "update_org":
      if (d.name) c.org.name = String(d.name);
      return { id: c.org.id };
    case "create_workflow": {
      const exist = byName(st.workflows, d.name);
      if (exist) return { id: exist.id };
      const problems = validateWorkflow(d.steps as WorkflowStep[], d.tier as Tier, c.org.regulated);
      if (problems.length) throw new Error(problems[0]);
      const w = wf(newId("wfl"), null, String(d.name), String(d.description ?? ""), d.tier as Tier, d.steps as WorkflowStep[]);
      w.content_type = str(d.content_type);
      st.workflows.push(w);
      return { id: w.id };
    }
    case "create_price_list": {
      const exist = byName(st.priceLists, d.name);
      if (exist) return { id: exist.id };
      const p: PriceList = { id: newId("prl"), name: String(d.name), currency: String(d.currency ?? "EUR"), rates: d.rates as PriceList["rates"], tm_weights: null, minimum_charge: null, archived: false, created_at: nowIso(), updated_at: nowIso() };
      st.priceLists.push(p);
      return { id: p.id };
    }
    case "create_account": {
      const exist = byName(st.accounts, d.name);
      if (exist) return { id: exist.id };
      const a2: Account = { id: newId("acc"), name: String(d.name), kind: (d.kind as Account["kind"]) ?? "client", status: "active", industry: null, country: null, vat_id: null, currency: "EUR", default_tier: null, workflow_template_id: byName(st.workflows, d.workflow)?.id ?? null, price_list_id: byName(st.priceLists, d.price_list)?.id ?? null, owner_user_id: null, notes: null, created_at: nowIso() };
      st.accounts.push(a2);
      return { id: a2.id };
    }
    case "create_dashboard": {
      const exist = byName(st.dashboards, d.name);
      if (exist) return { id: exist.id };
      const dash: Dashboard = { id: newId("dsh"), name: String(d.name), widgets: (d.widgets as Widget[]).map((w, i) => ({ ...w, id: `w${i + 1}`, title: METRIC_TITLES[w.metric] ?? w.metric })), is_default: false, created_at: nowIso(), updated_at: nowIso() };
      st.dashboards.push(dash);
      return { id: dash.id };
    }
    default:
      throw new Error(`The demo cannot apply ${a.type}`);
  }
}

// ---- router ----------------------------------------------------------------

export function agencyRoute(c: AgencyCtx): Response | null {
  const st = agencyStore();
  const { method: m, parts: p } = c;
  const [a, b, cc, d] = p;
  const pm = c.role === "pm";

  if (a === "crm") {
    if (!pm) return err(403, "forbidden", "CRM is for project managers.");
    if (b === "accounts" && !cc) {
      if (m === "GET") {
        const q = (c.q.get("q") ?? "").toLowerCase();
        const kind = c.q.get("kind");
        const status = c.q.get("status") ?? "active";
        return list(st.accounts.filter((x) => (!q || x.name.toLowerCase().includes(q)) && (!kind || x.kind === kind) && (!status || x.status === status)).sort((x, y) => x.name.localeCompare(y.name)), c.q);
      }
      if (m === "POST") {
        const body = c.body;
        if (!body.name) return err(422, "validation_error", "name is required");
        const x: Account = { id: newId("acc"), name: String(body.name), kind: (body.kind as Account["kind"]) ?? "client", status: "active", industry: str(body.industry), country: str(body.country), vat_id: str(body.vat_id), currency: str(body.currency) ?? "EUR", default_tier: (body.default_tier as Tier) ?? null, workflow_template_id: str(body.workflow_template_id), price_list_id: str(body.price_list_id), owner_user_id: "usr_01JPM", notes: str(body.notes), created_at: nowIso() };
        st.accounts.push(x);
        return json(accountDetail(st, x, c.jobs, c.projects), 201);
      }
    }
    if (b === "accounts" && cc) {
      const x = st.accounts.find((y) => y.id === cc);
      if (!x) return err(404, "not_found", "account not found");
      if (d === "contacts") {
        if (m === "GET") return list(st.contacts.filter((y) => y.account_id === x.id), c.q);
        if (m === "POST") {
          const ct: Contact = { id: newId("con"), account_id: x.id, name: String(c.body.name), email: str(c.body.email), phone: str(c.body.phone), role: str(c.body.role), is_primary: Boolean(c.body.is_primary), created_at: nowIso() };
          if (ct.is_primary) st.contacts.forEach((y) => y.account_id === x.id && (y.is_primary = false));
          st.contacts.push(ct);
          return json(ct, 201);
        }
      }
      if (!d && m === "GET") return json(accountDetail(st, x, c.jobs, c.projects));
      if (!d && m === "PATCH") {
        Object.assign(x, c.body);
        return json(accountDetail(st, x, c.jobs, c.projects));
      }
      if (!d && m === "DELETE") {
        x.status = "archived";
        return json(accountDetail(st, x, c.jobs, c.projects));
      }
    }
    if (b === "contacts" && cc) {
      const ct = st.contacts.find((y) => y.id === cc);
      if (!ct) return err(404, "not_found", "contact not found");
      if (m === "PATCH") return json(Object.assign(ct, c.body));
      if (m === "DELETE") {
        st.contacts = st.contacts.filter((y) => y.id !== cc);
        return new Response(null, { status: 204 });
      }
    }
    if (b === "deals" && !cc) {
      if (m === "GET") {
        const stage = c.q.get("stage");
        const aid = c.q.get("account_id");
        return list(st.deals.filter((x) => (!stage || x.stage === stage) && (!aid || x.account_id === aid)).sort((x, y) => y.updated_at.localeCompare(x.updated_at)), c.q);
      }
      if (m === "POST") {
        const acc = st.accounts.find((y) => y.id === c.body.account_id);
        if (!acc) return err(404, "not_found", "account not found");
        const x: Deal = { id: newId("dea"), account_id: acc.id, account_name: acc.name, title: String(c.body.title), value: Number(c.body.value ?? 0).toFixed(2), currency: String(c.body.currency ?? "EUR"), stage: (c.body.stage as DealStage) ?? "lead", expected_close: str(c.body.expected_close), quote_id: null, lost_reason: null, owner_user_id: "usr_01JPM", created_at: nowIso(), updated_at: nowIso() };
        st.deals.push(x);
        return json(x, 201);
      }
    }
    if (b === "deals" && cc) {
      const x = st.deals.find((y) => y.id === cc);
      if (!x) return err(404, "not_found", "deal not found");
      if (m === "PATCH") {
        Object.assign(x, c.body, { updated_at: nowIso() });
        if (c.body.value !== undefined) x.value = Number(c.body.value).toFixed(2);
        return json(x);
      }
      if (m === "DELETE") {
        st.deals = st.deals.filter((y) => y.id !== cc);
        return json(x);
      }
    }
    if (b === "activities" && !cc) {
      if (m === "GET") {
        const aid = c.q.get("account_id");
        const open = c.q.get("open");
        let xs = st.activities.filter((x) => (!aid || x.account_id === aid) && (open === null || (open === "true" ? !x.done : x.done)));
        xs = open === "true" ? xs.sort((x, y) => (x.due_at ?? "9").localeCompare(y.due_at ?? "9")) : xs.sort((x, y) => y.created_at.localeCompare(x.created_at));
        return list(xs, c.q);
      }
      if (m === "POST") {
        const x: Activity = { id: newId("act"), account_id: String(c.body.account_id), deal_id: str(c.body.deal_id), kind: c.body.kind as Activity["kind"], body: String(c.body.body), due_at: str(c.body.due_at), done: false, done_at: null, user_id: "usr_01JPM", created_at: nowIso() };
        st.activities.push(x);
        return json(x, 201);
      }
    }
    if (b === "activities" && cc && m === "PATCH") {
      const x = st.activities.find((y) => y.id === cc);
      if (!x) return err(404, "not_found", "activity not found");
      Object.assign(x, c.body);
      if (c.body.done !== undefined) x.done_at = c.body.done ? nowIso() : null;
      return json(x);
    }
  }

  if (a === "price-lists") {
    if (!pm) return err(403, "forbidden", "Price lists are for project managers.");
    if (!b && m === "GET") return list(st.priceLists.filter((x) => !x.archived), c.q);
    if (!b && m === "POST") {
      const x: PriceList = { id: newId("prl"), name: String(c.body.name), currency: String(c.body.currency ?? "EUR"), rates: (c.body.rates as PriceList["rates"]) ?? [], tm_weights: (c.body.tm_weights as PriceList["tm_weights"]) ?? null, minimum_charge: str(c.body.minimum_charge), archived: false, created_at: nowIso(), updated_at: nowIso() };
      if (!x.rates.length) return err(422, "validation_error", "at least one rate is required");
      st.priceLists.push(x);
      return json(x, 201);
    }
    const x = st.priceLists.find((y) => y.id === b);
    if (!x) return err(404, "not_found", "price list not found");
    if (m === "GET") return json(x);
    if (m === "PATCH") return json(Object.assign(x, c.body, { updated_at: nowIso() }));
    if (m === "DELETE") return json(Object.assign(x, { archived: true }));
  }

  if (a === "workflows") {
    if (!pm) return err(403, "forbidden", "Workflows are for project managers.");
    if (!b && m === "GET") return list([...st.workflows.filter((x) => !x.archived)].sort((x, y) => Number(x.preset !== null) - Number(y.preset !== null)), c.q);
    const validate = (steps: WorkflowStep[], tier: Tier) => {
      const problems = validateWorkflow(steps, tier, c.org.regulated);
      return problems.length ? err(422, "workflow_invalid", problems[0], { problems }) : null;
    };
    if (!b && m === "POST") {
      const bad = validate(c.body.steps as WorkflowStep[], c.body.tier as Tier);
      if (bad) return bad;
      const x = wf(newId("wfl"), null, String(c.body.name), String(c.body.description ?? ""), c.body.tier as Tier, c.body.steps as WorkflowStep[], Boolean(c.body.is_default));
      x.content_type = str(c.body.content_type);
      if (x.is_default) st.workflows.forEach((y) => (y.is_default = false));
      st.workflows.push(x);
      return json(x, 201);
    }
    const x = st.workflows.find((y) => y.id === b);
    if (!x) return err(404, "not_found", "workflow not found");
    if (m === "GET") return json(x);
    if (m === "PATCH") {
      const steps = (c.body.steps as WorkflowStep[]) ?? x.steps;
      const tier = (c.body.tier as Tier) ?? x.tier;
      const bad = validate(steps, tier);
      if (bad) return bad;
      if (c.body.is_default) st.workflows.forEach((y) => (y.is_default = false));
      return json(Object.assign(x, c.body, { updated_at: nowIso() }));
    }
    if (m === "DELETE") return json(Object.assign(x, { archived: true, is_default: false }));
  }

  if (a === "dashboards") {
    if (!pm && c.role !== "client") return err(403, "forbidden", "Dashboards are for customer users.");
    if (!b && m === "GET") return list(st.dashboards, c.q);
    if (b === "default" && m === "GET") return json(st.dashboards.find((x) => x.is_default) ?? st.dashboards[0]);
    const x = st.dashboards.find((y) => y.id === b);
    if (!x) return err(404, "not_found", "dashboard not found");
    if (!cc && m === "GET") return json(x);
    if (!cc && m === "PATCH") {
      if (!pm) return err(403, "forbidden", "Only project managers can edit dashboards.");
      if (c.body.name) x.name = String(c.body.name);
      if (Array.isArray(c.body.widgets))
        x.widgets = (c.body.widgets as Widget[]).map((w, i) => ({ ...w, id: w.id ?? `w${Date.now().toString(36)}${i}`, title: w.title || METRIC_TITLES[w.metric] || w.metric, size: w.size ?? "m" }));
      x.updated_at = nowIso();
      return json(x);
    }
    if (cc === "data" && m === "GET") {
      const period = (c.q.get("period") ?? "30d") as "30d" | "90d" | "365d";
      const days = { "30d": 30, "90d": 90, "365d": 365 }[period] ?? 30;
      const hide = c.role === "client";
      return json({
        period,
        currency: "EUR",
        generated_at: nowIso(),
        widgets: x.widgets.map((w) => {
          let data = widgetData(st, c, w, days) as Record<string, unknown> | null;
          if (hide && data && w.type === "kpi" && ["revenue", "margin", "margin_pct", "reviewer_cost"].includes(w.metric)) data = { ...data, value: null, previous: null };
          return { id: w.id, type: w.type, title: w.title ?? METRIC_TITLES[w.metric], data };
        }),
      });
    }
  }

  if (a === "assistant") {
    if (!pm) return err(403, "forbidden", "The assistant is for project managers.");
    if (b === "threads" && !cc) {
      if (m === "GET") return list([...st.threads].sort((x, y) => (y.updated_at ?? "").localeCompare(x.updated_at ?? "")), c.q);
      if (m === "POST") {
        const t: AssistantThread = { id: newId("thr"), title: String(c.body.title ?? ""), user_id: "usr_01JPM", created_at: nowIso(), updated_at: nowIso() };
        st.threads.push(t);
        return json({ ...t, messages: [] }, 201);
      }
    }
    if (b === "threads" && cc) {
      const t = st.threads.find((x) => x.id === cc);
      if (!t) return err(404, "not_found", "thread not found");
      if (!d && m === "GET") return json({ ...t, messages: st.messages.filter((x) => x.thread_id === t.id) });
      if (d === "messages" && m === "POST") {
        const content = String(c.body.content ?? "").trim();
        if (!content) return err(422, "validation_error", "content is required");
        const um: AssistantMessage = { id: newId("msg"), thread_id: t.id, role: "user", content, plan: null, applied: [], results: {}, created_at: nowIso() };
        const out = plan(content);
        const am: AssistantMessage = { id: newId("msg"), thread_id: t.id, role: "assistant", content: out.reply, plan: out.plan, applied: [], results: {}, created_at: nowIso() };
        st.messages.push(um, am);
        if (!t.title) t.title = content.slice(0, 60);
        t.updated_at = nowIso();
        return json({ user_message: um, assistant_message: am }, 201);
      }
    }
    if (b === "messages" && cc && d === "apply" && m === "POST") {
      const msg = st.messages.find((x) => x.id === cc);
      if (!msg || !msg.plan) return err(409, "conflict", "only an assistant message with a plan can be applied");
      const wanted = Array.isArray(c.body.actions) ? (c.body.actions as number[]) : msg.plan.map((_, i) => i);
      const results = msg.results ?? {};
      const out = wanted.map((i) => {
        const act = msg.plan![i];
        if (msg.applied.includes(i)) return { index: i, type: act.type, ok: true, id: results[String(i)]?.id, skipped: true };
        try {
          const r = applyAction(st, c, act, results);
          msg.applied = [...msg.applied, i].sort((x, y) => x - y);
          results[String(i)] = r;
          return { index: i, type: act.type, ok: true, id: r.id };
        } catch (e) {
          return { index: i, type: act.type, ok: false, error: e instanceof Error ? e.message : "failed" };
        }
      });
      msg.results = results;
      return json({ results: out, message: msg });
    }
  }
  return null;
}
