// Types mirroring docs/api-contract.md (v1).
// Money is a decimal string, times are ISO 8601 UTC strings, ids are prefixed strings.

export type Money = string;
export type ISODate = string;

export type Role = "admin" | "pm" | "client" | "reviewer";

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

export interface ListResponse<T> {
  items: T[];
  next_offset: number | null;
}

export interface ListParams {
  offset?: number;
  limit?: number;
}

// ---------- Auth and account ----------

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  org_id: string | null;
}

export type Tier = "auto" | "ai_review" | "hybrid" | "full";
export const TIERS: Tier[] = ["auto", "ai_review", "hybrid", "full"];

export type NoReviewerPolicy = "wait" | "ai_fallback" | "partial";

export interface Org {
  id: string;
  name: string;
  slug: string;
  plan: string;
  default_tier: Tier;
  no_reviewer_policy: NoReviewerPolicy;
  ai_subprocessors_opt_in: boolean;
  regulated: boolean;
  vertical: string | null;
  data_retention_days: number;
}

/** `GET /admin/orgs` (routes/admin.py). */
export interface OrgWithUsage extends Org {
  kind?: string;
  created_at?: ISODate | null;
  usage?: { period: string; words: number; jobs: number } | null;
}

export type OrgPatch = Partial<
  Pick<
    Org,
    | "name"
    | "default_tier"
    | "no_reviewer_policy"
    | "ai_subprocessors_opt_in"
    | "regulated"
    | "vertical"
    | "data_retention_days"
  >
>;

export interface AuthResponse {
  token: string;
  user: User;
  org?: Org | null;
}

export interface Me {
  user: User;
  org: Org | null;
}

export interface RegisterBody {
  org_name: string;
  name: string;
  email: string;
  password: string;
}

export interface LoginBody {
  email: string;
  password: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes?: string[];
  created_at?: ISODate;
  last_used_at?: ISODate | null;
}

export interface ApiKeyCreated {
  id: string;
  name: string;
  prefix: string;
  /** Full secret; returned once on creation only. */
  key: string;
}

// ---------- Files, quotes, projects, jobs ----------

export interface UploadedFile {
  id: string;
  filename: string;
  format: string;
  source_lang?: string;
  size?: number;
  segment_count: number;
  word_count: number;
  warnings: string[];
}

export interface TierQuote {
  price: Money;
  est_auto_rate: number; // 0..1
  eta_hours: number;
  available: boolean;
  blocked_reason?: string | null;
}

export interface Quote {
  id: string;
  file_id: string;
  source_lang: string;
  target_langs: string[];
  content_type: string;
  word_count: number;
  currency: string;
  valid_until: ISODate;
  analysis: {
    tm_context: number;
    tm_exact: number;
    tm_fuzzy: number;
    new: number;
    repetitions: number;
  };
  tiers: Record<Tier, TierQuote>;
}

export interface Project {
  id: string;
  name: string;
  source_lang: string;
  target_langs: string[];
  tier: Tier;
  content_type: string;
  due_at: ISODate | null;
  created_at: ISODate;
  jobs?: Job[];
  quote_id?: string;
  account_id?: string | null;
  workflow_template_id?: string | null;
}

/** Authority: services/api/arbiter/domain/states.py */
export type JobState =
  | "draft"
  | "quoted"
  | "running"
  | "review"
  | "ready"
  | "merging"
  | "delivered"
  | "settled"
  | "failed"
  | "cancelled"
  | "disputed";

/** States in which the translated file exists and can be downloaded. */
export const OUTPUT_STATES: JobState[] = ["delivered", "settled", "disputed"];
/** States in which nothing changes without a human (no polling needed). */
export const TERMINAL_JOB_STATES: JobState[] = ["delivered", "settled", "failed", "cancelled", "disputed"];

export interface Job {
  id: string;
  project_id: string;
  file_id: string;
  filename: string;
  source_lang: string;
  target_lang: string;
  tier: Tier;
  content_type: string;
  state: JobState;
  segment_count: number;
  word_count: number;
  auto_approved_count: number;
  review_count: number;
  ai_reviewed_count: number;
  progress: number; // 0..1
  threshold: number | null;
  /** Commercial fields; the UI only shows them to pm/admin. */
  revenue?: Money | null;
  cost?: Money | null;
  margin?: Money | null;
  failure_reason: string | null;
  due_at: ISODate | null;
  delivered_at: ISODate | null;
  created_at: ISODate;
  est_auto_rate?: number | null;
  no_reviewer_fallback_used?: boolean;
  started_at?: ISODate | null;
  // Agency OS
  account_id?: string | null;
  senate_count?: number;
  /** Frozen snapshot of the workflow the job runs (agency/workflows.py snapshot()). */
  workflow?: JobWorkflow | null;
  client_approved_at?: ISODate | null;
  awaiting_client_approval?: boolean;
}

export interface JobWorkflow {
  template_id: string | null;
  name: string;
  tier: Tier;
  source: "template" | "tier";
  steps: WorkflowStep[];
  client_review_requested_at?: ISODate | null;
}

/**
 * Authority: states.py. Blocked = needs_review with decision "blocked";
 * AI reviewed = reviewed with origin "editor".
 */
export type SegmentState = "pending" | "translated" | "auto_approved" | "needs_review" | "in_review" | "reviewed" | "delivered";

export const SEGMENT_STATES: SegmentState[] = [
  "pending",
  "translated",
  "auto_approved",
  "needs_review",
  "in_review",
  "reviewed",
  "delivered",
];

export type Decision =
  | "auto_approve"
  | "senate"
  | "review"
  | "blocked"
  | "ai_edit"
  | "ai_reviewed"
  | "ai_fallback"
  | "unreviewed"
  | "reviewed";
export const DECISIONS: Decision[] = [
  "auto_approve",
  "senate",
  "review",
  "blocked",
  "ai_edit",
  "ai_reviewed",
  "ai_fallback",
  "unreviewed",
  "reviewed",
];

export interface Segment {
  id: string;
  seq: number;
  source_tagged: string;
  /** null until the engine has produced a translation. */
  target_tagged: string | null;
  state: SegmentState;
  origin: string | null;
  engine: string | null;
  tm_match: number | null;
  qe_score: number | null; // 0..1
  decision: Decision | null;
  reasons: string[];
  signals: Record<string, unknown>;
  reviewer_id: string | null;
  is_control_sample: boolean;
  context?: string | null;
  max_length?: number | null;
  updated_at?: ISODate | null;
}

export interface SegmentQuery extends ListParams {
  state?: SegmentState | "";
  decision?: Decision | "";
}

export interface ExceptionItem {
  /** job_failed | segment_blocked | term_question | overdue */
  kind: string;
  term_question_id?: string;
  job_id: string;
  segment_id?: string | null;
  reason: string;
  created_at: ISODate;
}

// ---------- Linguistic assets ----------

export interface Glossary {
  id: string;
  name: string;
  content_type: string | null;
  version: number;
  term_count: number;
}

export type TermKind = "mandatory" | "preferred" | "forbidden" | "do_not_translate";
export const TERM_KINDS: TermKind[] = ["mandatory", "preferred", "forbidden", "do_not_translate"];

export interface Term {
  id: string;
  glossary_id: string;
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term: string | null;
  kind: TermKind;
  case_sensitive: boolean;
  note: string | null;
  valid_from: ISODate | null;
  valid_to: ISODate | null;
}

export interface TermInput {
  source_lang: string;
  target_lang: string;
  source_term: string;
  target_term?: string;
  kind: TermKind;
  case_sensitive?: boolean;
  note?: string;
}

export interface ImportResult {
  imported: number;
  skipped: number;
  errors?: string[];
}

export interface TmHit {
  entry_id: string;
  kind: string;
  /** 0..101 (101 = context match, 100 = exact). */
  score: number;
  source_tagged: string;
  target_tagged: string;
}

export interface TermQuestion {
  id: string;
  source_term: string;
  source_lang: string;
  target_lang: string;
  options: string[];
  status: string;
  answer?: string | null;
  job_id?: string | null;
  segment_id?: string | null;
  created_at?: ISODate;
}

// ---------- Quality ----------

export interface Threshold {
  id: string;
  content_type: string;
  target_lang: string;
  value: number;
  band_width: number;
  safety_offset: number;
  auto_approval_suspended: boolean;
  suspended_reason: string | null;
  last_calibrated_at?: ISODate | null;
}

/** Engine scoreboard row (routes/quality.py). */
export interface EngineScore {
  engine: string;
  source_lang: string;
  target_lang: string;
  domain: string | null;
  segments_measured: number;
  mean_qe: number | null;
  mean_edit_distance: number | null;
  term_adherence: number | null;
  updated_at?: ISODate | null;
}

export interface QualityDashboard {
  window_days?: number;
  segments?: number;
  auto_approved?: number;
  /** null when there is nothing to divide by. */
  auto_rate: number | null;
  escaped_errors?: number;
  escaped_rate: number | null;
  control_samples: { total: number; pending: number; ok: number; escaped: number };
  thresholds: Threshold[];
  engines: EngineScore[];
}

// ---------- Reviewers ----------

export interface LangPair {
  source_lang: string;
  target_lang: string;
}

export interface ReviewerPair extends LangPair {
  status: string;
  score: number | null;
}

export const REVIEWER_LEVELS = ["candidate", "reviewer", "senior", "domain_expert"] as const;
export type ReviewerLevel = (typeof REVIEWER_LEVELS)[number];
export const REVIEWER_STATUSES = ["applied", "active", "suspended", "banned"] as const;

export interface ReviewerProfile {
  id: string;
  user_id?: string;
  level: ReviewerLevel | string;
  status: string;
  /** 0..100 */
  score: number | null;
  pairs: ReviewerPair[];
  domains: string[];
  balance: Money;
  payout_threshold: Money;
  tax_info_complete: boolean;
  name?: string;
  email?: string;
  country?: string;
  payout_method?: string | null;
  decisions_total?: number;
  fraud_flags?: unknown;
  created_at?: ISODate | null;
}

export interface ReviewerApplyBody {
  name: string;
  email: string;
  password: string;
  country: string;
  pairs: LangPair[];
  domains: string[];
}

export interface ReviewerApplyResponse {
  token: string;
  user: User;
  profile: ReviewerProfile;
}

export type PayoutMethod = "sepa" | "wise" | "paypal";

export interface PayoutInfo {
  legal_name?: string;
  tax_id?: string;
  address?: string;
  /** YYYY-MM-DD */
  date_of_birth?: string;
  country?: string;
  payout_method?: PayoutMethod;
  payout_details?: Record<string, string>;
}

export interface ReviewerTest {
  id: string;
  kind: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  time_limit_min: number;
  status: "available" | "passed" | "failed" | "locked";
  pass_mark?: number;
  item_count?: number;
  retest_after?: ISODate | null;
}

export interface TestAttempt {
  attempt_id: string;
  test_id?: string;
  kind?: string;
  items: { index: number; source: string; target: string }[];
  time_limit_min: number;
  /** Server deadline; the timer uses it when present. */
  expires_at?: ISODate;
}

export type Severity = "minor" | "major" | "critical";
export const SEVERITIES: Severity[] = ["minor", "major", "critical"];

/** MQM-Core dimensions, exactly as services/api/arbiter/contracts.py MQM_DIMENSIONS. */
export const ERROR_DIMENSIONS = [
  "accuracy",
  "linguistic_conventions",
  "terminology",
  "style",
  "locale_conventions",
  "audience_appropriateness",
  "design_and_markup",
] as const;
export type ErrorDimension = (typeof ERROR_DIMENSIONS)[number];

/** Character offsets [start, end) of a selection; used in the UI only. */
export type Span = [number, number];

/**
 * The API identifies an error by the erroneous TEXT (`span: string`), matched by overlap
 * (community/testing.py `_overlaps`, review.py `_spans_overlap`).
 */
export interface TestAnswer {
  index: number;
  target: string;
  errors: { span: string; category: ErrorDimension; severity: Severity }[];
}

export interface Task {
  id: string;
  segment_id: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  source_tagged: string;
  target_tagged: string | null;
  context_before: string[] | string | null;
  context_after: string[] | string | null;
  word_count?: number;
  pay_estimate_edit?: Money;
  terms: { source_term: string; target_term: string | null; kind: TermKind }[];
  qe_score: number | null;
  flagged_errors: FlaggedError[];
  hold_expires_at: ISODate;
  pay_estimate: Money;
}

/** AI-flagged error on a task; the contract leaves the element shape open. */
export type FlaggedError =
  | string
  | {
      dimension?: string;
      category?: string;
      severity?: string;
      span?: string;
      role?: string;
      fix?: string | null;
      explanation?: string;
      message?: string;
    };

export type TaskDecision = "accept" | "edit" | "escalate" | "skip";

export interface TaskError {
  dimension: ErrorDimension;
  severity: Severity;
  /** The erroneous text. */
  span: string;
  explanation: string;
}

export interface TaskSubmit {
  decision: TaskDecision;
  target_tagged?: string;
  errors?: TaskError[];
  comment?: string;
  time_ms: number;
}

export interface LedgerEntry {
  id: string;
  kind: string;
  amount: Money;
  currency?: string;
  /** Reference to what caused the entry (task id, payout id, ...). */
  ref?: string | null;
  created_at: ISODate;
}

export interface Earnings {
  currency?: string;
  balance: Money;
  pending: Money;
  paid: Money;
  payout_threshold?: Money;
  entries: LedgerEntry[];
  rejected_tasks?: { task_id: string; state: string; submitted_at: ISODate | null }[];
}

// ---------- Admin ----------

export interface Dispute {
  id: string;
  task_id: string;
  reviewer_id?: string;
  reason: string;
  /** open | upheld | overturned | expired */
  status: string;
  decided_by?: string | null;
  decision_note?: string | null;
  due_at: ISODate;
  created_at?: ISODate | null;
  decided_at?: ISODate | null;
}

export interface Payout {
  id: string;
  reviewer_id: string;
  amount: Money;
  currency?: string;
  /** accrued | blocked | sent | settled | failed */
  state: string;
  method?: string | null;
  provider_ref?: string | null;
  failure_reason?: string | null;
  created_at: ISODate;
  sent_at?: ISODate | null;
}

export interface PayoutRun {
  created: number;
  total: Money;
  blocked?: number;
  retried?: number;
  provider?: string | null;
  note?: string;
}

// ---------- Integrations and billing ----------

export const WEBHOOK_EVENTS = [
  "job.delivered",
  "job.failed",
  "job.needs_attention",
  "quote.expired",
] as const;
export type WebhookEvent = (typeof WEBHOOK_EVENTS)[number];

export interface Webhook {
  id: string;
  url: string;
  events: WebhookEvent[];
  active: boolean;
  /** Only present on the create response. */
  secret?: string;
}

export interface Usage {
  period: string;
  words: number;
  /** Decimal string. */
  ai_units: string | number;
  review_decisions: number;
  storage_gb?: string;
  amount: Money;
}

export interface Invoice {
  id: string;
  number?: string;
  period?: string;
  subtotal?: Money;
  tax?: Money;
  total: Money;
  currency?: string;
  status: string;
  issued_at?: ISODate | null;
  created_at?: ISODate | null;
}

// ====================================================================== Agency OS

export type AccountKind = "client" | "prospect";

export interface Account {
  id: string;
  name: string;
  kind: AccountKind;
  status: "active" | "archived";
  industry: string | null;
  country: string | null;
  vat_id: string | null;
  currency: string | null;
  default_tier: Tier | null;
  workflow_template_id: string | null;
  price_list_id: string | null;
  owner_user_id: string | null;
  notes: string | null;
  created_at: ISODate;
}

export interface AccountStats {
  projects: number;
  jobs_active: number;
  revenue_total: Money | null;
  revenue_90d: Money | null;
  margin_90d: Money | null;
}

export interface AccountDetail extends Account {
  contacts: Contact[];
  deals: Deal[];
  recent_activities: Activity[];
  stats: AccountStats;
}

export interface AccountInput {
  name: string;
  kind: AccountKind;
  industry?: string | null;
  country?: string | null;
  vat_id?: string | null;
  currency?: string | null;
  default_tier?: Tier | null;
  workflow_template_id?: string | null;
  price_list_id?: string | null;
  notes?: string;
}

export interface Contact {
  id: string;
  account_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  is_primary: boolean;
  created_at?: ISODate;
}

export const DEAL_STAGES = ["lead", "qualified", "proposal", "negotiation", "won", "lost"] as const;
export type DealStage = (typeof DEAL_STAGES)[number];

export interface Deal {
  id: string;
  account_id: string;
  account_name: string | null;
  title: string;
  value: Money;
  currency: string;
  stage: DealStage;
  expected_close: string | null;
  quote_id: string | null;
  lost_reason: string | null;
  owner_user_id: string | null;
  closed_at?: ISODate | null;
  created_at: ISODate;
  updated_at: ISODate;
}

export const ACTIVITY_KINDS = ["note", "call", "email", "meeting", "task"] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export interface Activity {
  id: string;
  account_id: string;
  deal_id: string | null;
  kind: ActivityKind;
  body: string;
  due_at: ISODate | null;
  done: boolean;
  done_at?: ISODate | null;
  user_id: string | null;
  created_at: ISODate;
}

export interface Rate {
  source_lang?: string | null;
  target_lang?: string | null;
  tier: Tier;
  per_word: Money;
}

export const TM_WEIGHT_KEYS = ["context", "exact", "fuzzy_95", "fuzzy_85", "fuzzy_75", "new", "repetition"] as const;
export type TmWeightKey = (typeof TM_WEIGHT_KEYS)[number];

export interface PriceList {
  id: string;
  name: string;
  currency: string;
  rates: Rate[];
  tm_weights: Partial<Record<TmWeightKey, string | number>> | null;
  minimum_charge: Money | null;
  archived?: boolean;
  created_at?: ISODate;
  updated_at?: ISODate;
}

export interface PriceListInput {
  name: string;
  currency: string;
  rates: Rate[];
  tm_weights?: Partial<Record<TmWeightKey, string | number>> | null;
  minimum_charge?: Money | null;
}

export const STEP_KINDS = [
  "tm",
  "mt",
  "translation_senate",
  "qe",
  "senate",
  "ai_review",
  "human_review",
  "second_review",
  "client_review",
  "delivery",
] as const;
export type StepKind = (typeof STEP_KINDS)[number];

export interface WorkflowStep {
  kind: StepKind;
  params?: { engine?: string; threshold?: number; min_level?: "reviewer" | "senior" | "domain_expert" };
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  content_type: string | null;
  tier: Tier;
  steps: WorkflowStep[];
  is_default: boolean;
  /** Built-in preset key, null for custom templates. */
  preset: string | null;
  archived?: boolean;
  available?: boolean;
  blocked_reason?: string | null;
  created_at?: ISODate;
  updated_at?: ISODate;
}

export interface WorkflowInput {
  name: string;
  description?: string;
  content_type?: string | null;
  tier: Tier;
  steps: WorkflowStep[];
  is_default?: boolean;
}

export type WidgetType = "kpi" | "bar" | "line" | "table" | "pipeline";
export type WidgetSize = "s" | "m" | "l";

export interface Widget {
  id: string;
  type: WidgetType;
  metric: string;
  title?: string | null;
  size?: WidgetSize;
}

export interface Dashboard {
  id: string;
  name: string;
  widgets: Widget[];
  is_default?: boolean;
  created_at?: ISODate;
  updated_at?: ISODate;
}

export type DashboardPeriod = "30d" | "90d" | "365d";

export interface KpiData {
  value: number | string | null;
  /** currency code, "%", "ratio", "jobs", "words" */
  unit: string;
  previous?: number | string | null;
  count?: number;
}
export interface SeriesData {
  unit: string;
  points: { label: string; value: number | string | null; id?: string }[];
}
export interface PipelineData {
  currency: string;
  stages: { stage: DealStage; count: number; value: Money | null }[];
}
export interface TableData {
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface DashboardData {
  period: DashboardPeriod;
  currency?: string;
  generated_at?: ISODate;
  widgets: { id: string; type: WidgetType; title: string | null; data: KpiData | SeriesData | PipelineData | TableData }[];
}

export const ACTION_TYPES = [
  "create_workflow",
  "create_price_list",
  "create_account",
  "create_contact",
  "create_deal",
  "create_activity",
  "create_dashboard",
  "update_org",
  "create_glossary",
  "add_terms",
  "create_webhook",
] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export interface PlanAction {
  type: ActionType | string;
  summary: string;
  data: Record<string, unknown>;
}

export interface AssistantMessage {
  id: string;
  thread_id?: string;
  role: "user" | "assistant";
  /** The text: the user's prompt or the assistant's reply. */
  content: string;
  plan: PlanAction[] | null;
  applied: number[];
  results?: Record<string, { id?: string }>;
  created_at: ISODate;
}

export interface AssistantThread {
  id: string;
  title: string;
  user_id?: string | null;
  created_at: ISODate;
  updated_at?: ISODate;
  messages?: AssistantMessage[];
}

export interface ApplyResult {
  index: number;
  type: string;
  ok: boolean;
  id?: string | null;
  error?: string;
  note?: string;
  warnings?: string[];
  skipped?: boolean;
}
