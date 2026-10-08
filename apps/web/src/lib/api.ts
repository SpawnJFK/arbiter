// Typed API client for the Arbiter v1 contract (docs/api-contract.md).
//
// The same endpoint map runs on two transports:
//  - `api` (this module's default) talks to `/api/proxy/*`, a Next route handler that
//    attaches the httpOnly session token. Use it from Client Components.
//  - `getServerApi()` in `server-api.ts` calls the backend directly with the Bearer token
//    read from the cookie. Use it from Server Components and route handlers.
// In mock mode (NEXT_PUBLIC_API_MOCK=1) the server side answers from src/lib/mock, so both
// transports see the same fixture data.

import type {
  Account,
  AccountDetail,
  AccountInput,
  Activity,
  ApplyResult,
  AssistantMessage,
  AssistantThread,
  Contact,
  Dashboard,
  DashboardData,
  DashboardPeriod,
  Deal,
  DealStage,
  PriceList,
  PriceListInput,
  Widget,
  Workflow,
  WorkflowInput,
  ApiErrorBody,
  ApiKey,
  ApiKeyCreated,
  Dispute,
  Earnings,
  ExceptionItem,
  Glossary,
  ImportResult,
  Invoice,
  Job,
  JobState,
  ListParams,
  ListResponse,
  Me,
  Org,
  OrgPatch,
  OrgWithUsage,
  Payout,
  PayoutRun,
  PayoutInfo,
  Project,
  QualityDashboard,
  Quote,
  ReviewerProfile,
  ReviewerTest,
  Segment,
  SegmentQuery,
  Task,
  TaskSubmit,
  Term,
  TermInput,
  TermQuestion,
  TestAnswer,
  TestAttempt,
  Threshold,
  Tier,
  TmHit,
  UploadedFile,
  Usage,
  Webhook,
  WebhookEvent,
} from "./types";
import type { LocaleInfo } from "./i18n/locales";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: FormData;
  idempotencyKey?: string;
}

export interface Transport {
  /** Resolves to parsed JSON, or `null` for 204 No Content. Throws ApiError on non-2xx. */
  request<T>(method: string, path: string, opts?: RequestOptions): Promise<T>;
  /** Browser-usable URL for binary downloads (exports, evidence packs). */
  downloadUrl(path: string, query?: Query): string;
}

export function toQueryString(query?: Query): string {
  if (!query) return "";
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await res.json()) as Partial<ApiErrorBody>;
  } catch {
    body = null;
  }
  const err = body?.error;
  return new ApiError(
    res.status,
    err?.code ?? `http_${res.status}`,
    err?.message || res.statusText || `HTTP ${res.status}`,
    err?.details ?? {},
  );
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Transport used in the browser: everything goes through the same-origin proxy route. */
export const proxyTransport: Transport = {
  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: BodyInit | undefined;
    if (opts.form) {
      body = opts.form;
    } else if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
    const res = await fetch(`/api/proxy${path}${toQueryString(opts.query)}`, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
    });
    if (res.status === 401 && typeof window !== "undefined") {
      // Hard navigation on purpose: drops all client state of the expired session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/logout?next=${encodeURIComponent(window.location.pathname)}`);
    }
    if (!res.ok) throw await parseError(res);
    if (res.status === 204) return null as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : null) as T;
  },
  downloadUrl(path: string, query?: Query) {
    return `/api/proxy${path}${toQueryString(query)}`;
  },
};

const enc = encodeURIComponent;

export function createApi(item: Transport) {
  const get = <T>(path: string, query?: Query) => item.request<T>("GET", path, { query });
  const post = <T>(path: string, body?: unknown, idem = false) =>
    item.request<T>("POST", path, { body, idempotencyKey: idem ? newIdempotencyKey() : undefined });
  const patch = <T>(path: string, body: unknown) => item.request<T>("PATCH", path, { body });
  const del = (path: string) => item.request<null>("DELETE", path);
  const page = (p?: ListParams): Query => ({ offset: p?.offset, limit: p?.limit });

  return {
    downloadUrl: item.downloadUrl,

    // Auth and account (login/register are handled by /api/session, not here)
    me: () => get<Me>("/me"),
    org: () => get<Org>("/org"),
    updateOrg: (body: OrgPatch) => patch<Org>("/org", body),
    apiKeys: () => get<ListResponse<ApiKey>>("/api-keys"),
    createApiKey: (body: { name: string; scopes: string[] }) => post<ApiKeyCreated>("/api-keys", body, true),
    deleteApiKey: (id: string) => del(`/api-keys/${enc(id)}`),

    // Files, quotes, projects, jobs
    uploadFile: (file: File, sourceLang: string) => {
      const form = new FormData();
      form.set("file", file);
      form.set("source_lang", sourceLang);
      return item.request<UploadedFile>("POST", "/files", { form, idempotencyKey: newIdempotencyKey() });
    },
    createQuote: (body: { file_id: string; target_langs: string[]; content_type: string; account_id?: string }) =>
      post<Quote>("/quotes", body, true),
    quote: (id: string) => get<Quote>(`/quotes/${enc(id)}`),
    createProject: (body: {
      name: string;
      quote_id: string;
      tier?: Tier;
      due_at?: string;
      account_id?: string;
      workflow_template_id?: string;
    }) =>
      post<Project>("/projects", body, true),
    projects: (p?: ListParams) => get<ListResponse<Project>>("/projects", page(p)),
    project: (id: string) => get<Project>(`/projects/${enc(id)}`),
    jobs: (q: { state?: JobState; project_id?: string } & ListParams = {}) =>
      get<ListResponse<Job>>("/jobs", { ...q }),
    job: (id: string) => get<Job>(`/jobs/${enc(id)}`),
    segments: (jobId: string, q: SegmentQuery = {}) =>
      get<ListResponse<Segment>>(`/jobs/${enc(jobId)}/segments`, { ...q }),
    editSegment: (jobId: string, segId: string, target_tagged: string) =>
      patch<Segment>(`/jobs/${enc(jobId)}/segments/${enc(segId)}`, { target_tagged }),
    approveSegment: (jobId: string, segId: string) =>
      post<Segment>(`/jobs/${enc(jobId)}/segments/${enc(segId)}/approve`),
    cancelJob: (jobId: string) => post<Job>(`/jobs/${enc(jobId)}/cancel`),
    clientApprove: (jobId: string) => post<Job>(`/jobs/${enc(jobId)}/client-approve`),
    reportError: (jobId: string, body: { segment_id: string; note: string }) =>
      post<{ id: string }>(`/jobs/${enc(jobId)}/report-error`, body, true),
    jobDownloadUrl: (jobId: string) => item.downloadUrl(`/jobs/${enc(jobId)}/download`),
    jobXliffUrl: (jobId: string) => item.downloadUrl(`/jobs/${enc(jobId)}/xliff`),
    jobEvidenceUrl: (jobId: string, format: "json" | "pdf") =>
      item.downloadUrl(`/jobs/${enc(jobId)}/evidence`, { format }),
    exceptions: (p?: ListParams) => get<ListResponse<ExceptionItem>>("/exceptions", page(p)),

    // Linguistic assets
    glossaries: (p?: ListParams) => get<ListResponse<Glossary>>("/glossaries", page(p)),
    createGlossary: (body: { name: string; content_type?: string }) => post<Glossary>("/glossaries", body, true),
    terms: (glossaryId: string, q: { q?: string; source_lang?: string; target_lang?: string } & ListParams = {}) =>
      get<ListResponse<Term>>(`/glossaries/${enc(glossaryId)}/terms`, { ...q }),
    createTerm: (glossaryId: string, body: TermInput) =>
      post<Term>(`/glossaries/${enc(glossaryId)}/terms`, body, true),
    updateTerm: (id: string, body: Partial<TermInput>) => patch<Term>(`/terms/${enc(id)}`, body),
    retireTerm: (id: string) => del(`/terms/${enc(id)}`),
    importGlossary: (glossaryId: string, file: File) => {
      const form = new FormData();
      form.set("file", file);
      return item.request<ImportResult>("POST", `/glossaries/${enc(glossaryId)}/import`, {
        form,
        idempotencyKey: newIdempotencyKey(),
      });
    },
    glossaryExportUrl: (glossaryId: string, format: "csv" | "tbx") =>
      item.downloadUrl(`/glossaries/${enc(glossaryId)}/export`, { format }),
    importTm: (file: File) => {
      const form = new FormData();
      form.set("file", file);
      form.set("rights_confirmed", "true");
      return item.request<ImportResult>("POST", "/tm/import", { form, idempotencyKey: newIdempotencyKey() });
    },
    tmSearch: (q: { q?: string; source_lang?: string; target_lang?: string } & ListParams) =>
      get<ListResponse<TmHit>>("/tm/search", { ...q }),
    tmExportUrl: (q: { source_lang?: string; target_lang?: string }) => item.downloadUrl("/tm/export", q),
    termQuestions: (p?: ListParams) => get<ListResponse<TermQuestion>>("/term-questions", page(p)),
    answerTermQuestion: (id: string, body: { answer: string; add_to_glossary_id?: string }) =>
      post<TermQuestion>(`/term-questions/${enc(id)}/answer`, body),

    // Quality
    qualityDashboard: () => get<QualityDashboard>("/quality/dashboard"),
    thresholds: () => get<ListResponse<Threshold>>("/quality/thresholds"),

    // Reviewer
    reviewerMe: () => get<ReviewerProfile>("/reviewer/me"),
    updateReviewerMe: (body: PayoutInfo) => patch<ReviewerProfile>("/reviewer/me", body),
    reviewerTests: () => get<ListResponse<ReviewerTest>>("/reviewer/tests"),
    startTest: (id: string) => post<TestAttempt>(`/reviewer/tests/${enc(id)}/start`),
    submitAttempt: (attemptId: string, answers: TestAnswer[]) =>
      post<{ score: number; passed: boolean }>(`/reviewer/attempts/${enc(attemptId)}/submit`, { answers }),
    /** Resolves to `null` when the queue is empty (HTTP 204). */
    nextTask: (body: { source_lang?: string; target_lang?: string } = {}) =>
      item.request<Task | null>("POST", "/reviewer/tasks/next", { body }),
    submitTask: (id: string, body: TaskSubmit) =>
      post<{ ok: boolean; pay_amount: string }>(`/reviewer/tasks/${enc(id)}/submit`, body),
    releaseTask: (id: string) => post<null>(`/reviewer/tasks/${enc(id)}/release`),
    earnings: () => get<Earnings>("/reviewer/earnings"),
    createDispute: (body: { task_id: string; reason: string }) =>
      post<{ id: string; due_at: string }>("/reviewer/disputes", body, true),

    // Admin
    adminReviewers: (q: { status?: string } & ListParams = {}) =>
      get<ListResponse<ReviewerProfile>>("/admin/reviewers", { ...q }),
    setReviewerStatus: (id: string, body: { status: string; level?: string }) =>
      post<ReviewerProfile>(`/admin/reviewers/${enc(id)}/status`, body),
    adminDisputes: (p?: ListParams) => get<ListResponse<Dispute>>("/admin/disputes", page(p)),
    decideDispute: (id: string, body: { outcome: "upheld" | "overturned"; note: string }) =>
      post<Dispute>(`/admin/disputes/${enc(id)}/decide`, body),
    adminPayouts: (p?: ListParams) => get<ListResponse<Payout>>("/admin/payouts", page(p)),
    runPayouts: () => post<PayoutRun>("/admin/payouts/run", undefined, true),
    adminOrgs: (p?: ListParams) => get<ListResponse<OrgWithUsage>>("/admin/orgs", page(p)),

    // --- UI localization (reads are public; admins also see disabled locales)
    i18nLocales: () => get<{ items: LocaleInfo[] }>("/i18n/locales"),
    i18nMessages: (locale: string) => get<{ locale: string; messages: Record<string, string> }>(`/i18n/messages/${enc(locale)}`),

    // Agency OS: CRM
    accounts: (q: { q?: string; kind?: string; status?: string } & ListParams = {}) =>
      get<ListResponse<Account>>("/crm/accounts", { ...q }),
    account: (id: string) => get<AccountDetail>(`/crm/accounts/${enc(id)}`),
    createAccount: (body: AccountInput) => post<AccountDetail>("/crm/accounts", body, true),
    updateAccount: (id: string, body: Partial<AccountInput> & { status?: "active" | "archived" }) =>
      patch<AccountDetail>(`/crm/accounts/${enc(id)}`, body),
    archiveAccount: (id: string) => item.request<AccountDetail>("DELETE", `/crm/accounts/${enc(id)}`),
    contacts: (accountId: string) => get<ListResponse<Contact>>(`/crm/accounts/${enc(accountId)}/contacts`),
    createContact: (accountId: string, body: Omit<Contact, "id" | "account_id" | "created_at">) =>
      post<Contact>(`/crm/accounts/${enc(accountId)}/contacts`, body, true),
    updateContact: (id: string, body: Partial<Omit<Contact, "id" | "account_id">>) =>
      patch<Contact>(`/crm/contacts/${enc(id)}`, body),
    deleteContact: (id: string) => del(`/crm/contacts/${enc(id)}`),
    deals: (q: { stage?: DealStage; account_id?: string } & ListParams = {}) =>
      get<ListResponse<Deal>>("/crm/deals", { ...q }),
    createDeal: (body: { account_id: string; title: string; value: string; currency?: string; stage?: DealStage; expected_close?: string }) =>
      post<Deal>("/crm/deals", body, true),
    updateDeal: (id: string, body: { stage?: DealStage; value?: string; title?: string; expected_close?: string | null; lost_reason?: string }) =>
      patch<Deal>(`/crm/deals/${enc(id)}`, body),
    deleteDeal: (id: string) => item.request<Deal>("DELETE", `/crm/deals/${enc(id)}`),
    activities: (q: { account_id?: string; deal_id?: string; open?: boolean } & ListParams = {}) =>
      get<ListResponse<Activity>>("/crm/activities", { ...q }),
    createActivity: (body: { account_id: string; deal_id?: string; kind: Activity["kind"]; body: string; due_at?: string }) =>
      post<Activity>("/crm/activities", body, true),
    updateActivity: (id: string, body: { done?: boolean; body?: string; due_at?: string | null }) =>
      patch<Activity>(`/crm/activities/${enc(id)}`, body),

    // Agency OS: price lists, workflows
    priceLists: (p?: ListParams) => get<ListResponse<PriceList>>("/price-lists", page(p)),
    priceList: (id: string) => get<PriceList>(`/price-lists/${enc(id)}`),
    createPriceList: (body: PriceListInput) => post<PriceList>("/price-lists", body, true),
    updatePriceList: (id: string, body: Partial<PriceListInput>) => patch<PriceList>(`/price-lists/${enc(id)}`, body),
    archivePriceList: (id: string) => item.request<PriceList>("DELETE", `/price-lists/${enc(id)}`),
    workflows: (p?: ListParams) => get<ListResponse<Workflow>>("/workflows", page(p)),
    workflow: (id: string) => get<Workflow>(`/workflows/${enc(id)}`),
    createWorkflow: (body: WorkflowInput) => post<Workflow>("/workflows", body, true),
    updateWorkflow: (id: string, body: Partial<WorkflowInput>) => patch<Workflow>(`/workflows/${enc(id)}`, body),
    archiveWorkflow: (id: string) => item.request<Workflow>("DELETE", `/workflows/${enc(id)}`),

    // Agency OS: dashboards
    defaultDashboard: () => get<Dashboard>("/dashboards/default"),
    dashboards: () => get<ListResponse<Dashboard>>("/dashboards"),
    dashboard: (id: string) => get<Dashboard>(`/dashboards/${enc(id)}`),
    updateDashboard: (id: string, body: { name?: string; widgets?: Omit<Widget, "id">[] | Widget[] }) =>
      patch<Dashboard>(`/dashboards/${enc(id)}`, body),
    dashboardData: (id: string, period: DashboardPeriod) =>
      get<DashboardData>(`/dashboards/${enc(id)}/data`, { period }),

    // Agency OS: assistant
    threads: () => get<ListResponse<AssistantThread>>("/assistant/threads"),
    thread: (id: string) => get<AssistantThread>(`/assistant/threads/${enc(id)}`),
    createThread: (title?: string) => post<AssistantThread>("/assistant/threads", { title }, true),
    /** `locale` is the UI language; the assistant replies in it. */
    sendMessage: (threadId: string, content: string, locale?: string) =>
      post<{ user_message: AssistantMessage; assistant_message: AssistantMessage }>(
        `/assistant/threads/${enc(threadId)}/messages`,
        { content, locale },
        true,
      ),
    applyPlan: (messageId: string, actions?: number[]) =>
      post<{ results: ApplyResult[]; message?: AssistantMessage }>(`/assistant/messages/${enc(messageId)}/apply`, {
        actions,
      }),

    // Integrations and billing
    webhooks: () => get<ListResponse<Webhook>>("/webhooks"),
    createWebhook: (body: { url: string; events: WebhookEvent[] }) => post<Webhook>("/webhooks", body, true),
    deleteWebhook: (id: string) => del(`/webhooks/${enc(id)}`),
    usage: (period?: string) => get<Usage>("/usage", { period }),
    invoices: (p?: ListParams) => get<ListResponse<Invoice>>("/invoices", page(p)),
  };
}

export type Api = ReturnType<typeof createApi>;

/** Browser client. Safe to import from Client Components: the token never leaves the server. */
export const api: Api = createApi(proxyTransport);

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}
