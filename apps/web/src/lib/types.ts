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

/** `GET /admin/orgs` returns "Org with usage"; the usage shape is not pinned in the contract. */
export interface OrgWithUsage extends Org {
  usage?: Partial<Usage> | null;
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
}

export type JobState =
  | "draft"
  | "queued"
  | "preparing"
  | "translating"
  | "scoring"
  | "review"
  | "merging"
  | "delivered"
  | "failed"
  | "cancelled"
  | "disputed";

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
}

export type SegmentState =
  | "pending"
  | "translated"
  | "scored"
  | "auto_approved"
  | "in_review"
  | "reviewed"
  | "ai_reviewed"
  | "approved"
  | "delivered"
  | "needs_review"
  | "blocked";

export const SEGMENT_STATES: SegmentState[] = [
  "pending",
  "translated",
  "scored",
  "auto_approved",
  "in_review",
  "reviewed",
  "ai_reviewed",
  "approved",
  "delivered",
  "needs_review",
  "blocked",
];

export type Decision = "auto_approve" | "senate" | "review" | "blocked";
export const DECISIONS: Decision[] = ["auto_approve", "senate", "review", "blocked"];

export interface Segment {
  id: string;
  seq: number;
  source_tagged: string;
  target_tagged: string;
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
}

export interface SegmentQuery extends ListParams {
  state?: SegmentState | "";
  decision?: Decision | "";
}

export interface ExceptionItem {
  kind: string;
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
}

/** Engine rows are not pinned in the contract; fields are read defensively. */
export interface EngineScore {
  engine: string;
  segments?: number;
  avg_qe?: number;
  auto_rate?: number;
  escaped_rate?: number;
  win_rate?: number;
}

export interface QualityDashboard {
  auto_rate: number;
  escaped_rate: number;
  control_samples: number;
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

export interface ReviewerProfile {
  id: string;
  /** Not pinned in the contract; displayed as-is, admin sets it 1..4. */
  level: number | string;
  status: string;
  score: number | null;
  pairs: ReviewerPair[];
  domains: string[];
  balance: Money;
  payout_threshold: Money;
  tax_info_complete: boolean;
  // Admin listings may include identity fields; optional.
  name?: string;
  email?: string;
  country?: string;
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

export type PayoutMethod = "bank_transfer" | "paypal" | "wise";

export interface PayoutInfo {
  legal_name?: string;
  tax_id?: string;
  address?: string;
  date_of_birth?: string;
  payout_method?: PayoutMethod;
  payout_details?: string;
}

export interface ReviewerTest {
  id: string;
  kind: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  time_limit_min: number;
  status: "available" | "passed" | "failed" | "locked";
}

export interface TestAttempt {
  attempt_id: string;
  items: { index: number; source: string; target: string }[];
  time_limit_min: number;
}

export type Severity = "minor" | "major" | "critical";
export const SEVERITIES: Severity[] = ["minor", "major", "critical"];

/** Error dimensions follow MQM top-level categories (the contract does not enumerate them). */
export const ERROR_DIMENSIONS = [
  "accuracy",
  "fluency",
  "terminology",
  "style",
  "locale_convention",
  "markup",
] as const;
export type ErrorDimension = (typeof ERROR_DIMENSIONS)[number];

/** Character offsets [start, end) into the submitted target string, tags included. */
export type Span = [number, number];

export interface TestAnswer {
  index: number;
  target: string;
  errors: { span: Span; category: ErrorDimension; severity: Severity }[];
}

export interface Task {
  id: string;
  segment_id: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  source_tagged: string;
  target_tagged: string;
  context_before: string[] | string | null;
  context_after: string[] | string | null;
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
      span?: Span | string;
      explanation?: string;
      message?: string;
    };

export type TaskDecision = "accept" | "edit" | "escalate" | "skip";

export interface TaskError {
  dimension: ErrorDimension;
  severity: Severity;
  span: Span;
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
  created_at: ISODate;
  description?: string | null;
  task_id?: string | null;
  state?: string | null;
}

export interface Earnings {
  balance: Money;
  pending: Money;
  paid: Money;
  entries: LedgerEntry[];
}

// ---------- Admin ----------

export interface Dispute {
  id: string;
  task_id: string;
  reviewer_id?: string;
  reason: string;
  status: string;
  outcome?: "upheld" | "overturned" | null;
  note?: string | null;
  due_at: ISODate;
  created_at?: ISODate;
}

export interface Payout {
  id: string;
  reviewer_id: string;
  amount: Money;
  state: string;
  created_at: ISODate;
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
  ai_units: number;
  review_decisions: number;
  amount: Money;
}

export interface Invoice {
  id: string;
  period?: string;
  number?: string;
  amount: Money;
  currency?: string;
  status: string;
  issued_at?: ISODate;
  pdf_url?: string | null;
}
