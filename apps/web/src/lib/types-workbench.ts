// Types for the workbench and TM tools (module tms), LQA scorecards (module ai) and the
// auditor (module auditor). Mirrors docs/api-contract.md, section "Workbench, TM tools, LQA, auditor".

import type { ISODate, ListResponse, Money, Segment, SegmentState, TermKind } from "./types";

// ---------- Workbench ----------

export interface EditorSegment extends Segment {
  unit_id: string;
  seg_index: number;
  word_count: number;
  locked: boolean;
  locked_by: string | null;
  locked_at: ISODate | null;
  qa_count: number;
  comment_threads: number;
  open_queries: number;
  slots: number;
}

export interface EditorSegmentPage extends ListResponse<EditorSegment> {
  total: number;
}

export type TmBand = "none" | "lt75" | "75-84" | "85-94" | "95-99" | "100" | "101";
export const TM_BANDS: TmBand[] = ["none", "lt75", "75-84", "85-94", "95-99", "100", "101"];

export interface EditorFilters {
  state?: string;
  decision?: string;
  locked?: string;
  has_comment?: string;
  open_query?: string;
  qa?: string;
  tm_band?: string;
  q?: string;
}

export interface QaIssueItem {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  blocking: boolean;
}

export interface TermHitItem {
  term_id: string;
  kind: TermKind;
  source_term: string;
  target_term: string | null;
  start: number;
  end: number;
  note: string;
}

export interface DraftCheck {
  issues: QaIssueItem[];
  blocking: boolean;
  terms: TermHitItem[];
  term_violations: { term_id: string; code: string; severity: string; message: string }[];
}

export interface DiffOp {
  op: "equal" | "insert" | "delete";
  text: string;
}

export interface TmMatchWithDiff {
  entry_id: string;
  kind: string;
  score: number;
  source_tagged: string;
  target_tagged: string;
  diff: DiffOp[];
}

export interface AssistData {
  tm_matches: TmMatchWithDiff[];
  terms: TermHitItem[];
}

export interface MtSuggestion {
  target_tagged: string;
  engine: string;
  model_version: string;
}

export interface FindReplaceInput {
  find: string;
  replace?: string | null;
  regex?: boolean;
  case_sensitive?: boolean;
  whole_word?: boolean;
  scope?: "target" | "source" | "both";
  states?: string[];
  segment_ids?: string[];
  apply?: boolean;
  force?: boolean;
}

export type SkipReason = "locked" | "approved" | "state" | "tag_error" | "unchanged";

export interface FindReplaceItem {
  segment_id: string;
  seq: number;
  state: SegmentState;
  locked: boolean;
  source_matches: number;
  target_matches: number;
  source_tagged: string;
  before: string | null;
  after: string | null;
  skip_reason: SkipReason | null;
}

export interface FindReplaceResult {
  items: FindReplaceItem[];
  total_matches: number;
  segments: number;
  changed: number;
  skipped: number;
  applied: boolean;
}

export interface SegmentComment {
  id: string;
  job_id: string;
  segment_id: string | null;
  thread_id: string;
  parent_id: string | null;
  kind: "comment" | "query";
  author_id: string;
  author_role: string;
  body: string;
  mentions: string[];
  resolved: boolean;
  resolved_by: string | null;
  resolved_at: ISODate | null;
  created_at: ISODate;
}

export interface QueryItem extends SegmentComment {
  filename: string | null;
  segment_seq: number | null;
  source_tagged: string | null;
  target_tagged: string | null;
  replies: SegmentComment[];
}

export interface ConcordanceHit {
  entry_id: string;
  source_tagged: string;
  target_tagged: string;
  score: number;
  origin: string;
  updated_at: ISODate | null;
}

// ---------- TM tools ----------

export interface TmEntryRow {
  id: string;
  source_lang: string;
  target_lang: string;
  content_type: string;
  source_tagged: string;
  target_tagged: string;
  status: "approved" | "imported" | "stale";
  origin: string;
  job_id: string | null;
  has_context: boolean;
  rights_confirmed_by: string | null;
  created_at: ISODate | null;
  updated_at: ISODate | null;
}

export interface TmEntryQuery {
  q?: string;
  source_lang?: string;
  target_lang?: string;
  origin?: string;
  status?: string;
  created_from?: string;
  created_to?: string;
  offset?: number;
  limit?: number;
}

export interface AlignmentPair {
  index: number;
  src: number[];
  tgt: number[];
  source: string;
  target: string;
  confidence: number;
  accepted: boolean;
}

export interface Alignment {
  id: string;
  source_lang: string;
  target_lang: string;
  source_filename: string;
  target_filename: string;
  status: "review" | "committed";
  committed_count: number;
  pairs: AlignmentPair[];
  stats: { pairs: number; one_to_one: number; unaligned: number; low_confidence: number };
  created_at: ISODate | null;
}

export interface TermCandidate {
  source_term: string;
  frequency: number;
  words: number;
  variants: string[];
  target_candidates: { term: string; score: number; count: number }[];
}

export interface TermExtraction {
  source_lang: string;
  target_lang: string;
  job_id: string | null;
  filename: string | null;
  items: TermCandidate[];
}

export interface TmQa {
  inconsistent: {
    source_tagged: string;
    source_lang: string;
    target_lang: string;
    variants: { target_tagged: string; entry_ids: string[]; origins: string[]; updated_at: ISODate | null }[];
  }[];
  glossary_violations: {
    entry_id: string;
    source_tagged: string;
    target_tagged: string;
    violations: { code: string; term_id: string; message: string }[];
  }[];
}

// ---------- LQA ----------

export type MqmSeverity = "neutral" | "minor" | "major" | "critical";
export const MQM_SEVERITIES: MqmSeverity[] = ["neutral", "minor", "major", "critical"];

export type DimensionCounts = Record<MqmSeverity, number> & { penalty: number };

export interface LqaCard {
  word_count: number;
  error_count: number;
  by_dimension: Record<string, DimensionCounts>;
  by_severity: Record<MqmSeverity, number>;
  penalty: number;
  score: number;
  threshold: number;
  passed: boolean;
  weights: Record<string, number>;
}

export interface LqaErrorRow {
  dimension: string;
  severity: MqmSeverity;
  span: string;
  explanation: string;
  source: string;
  seq?: number;
  segment_id?: string;
  source_text?: string;
  target_text?: string;
}

export interface JobLqa extends LqaCard {
  job_id: string;
  segments_with_errors: number;
  sources: { reviewer: number; senate: number };
  errors: LqaErrorRow[];
}

export interface LqaSettings {
  threshold: number;
  weights: Record<string, number>;
  dimensions: string[];
}

// ---------- Auditor ----------

export type AuditState = "queued" | "running" | "done" | "failed";
export type AiMode = "none" | "sample" | "full";

export interface AuditIssue {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
  blocking: boolean;
  kind: "qa" | "term" | "consistency";
  dimension: string;
  mqm_severity: MqmSeverity;
}

export interface Audit {
  id: string;
  name: string;
  source_lang: string;
  target_lang: string;
  input_format: "xliff" | "tmx" | "csv" | "xlsx" | "pair";
  filename: string;
  target_filename: string | null;
  glossary_id: string | null;
  settings: { ai_mode?: AiMode; ai_sample_pct?: number; threshold?: number | null; consistency?: boolean };
  state: AuditState;
  progress: number;
  segments_total: number;
  segments_done: number;
  word_count: number;
  mqm_score: number | null;
  verdict: "pass" | "fail" | null;
  ai_units: Money;
  summary: {
    segments?: number;
    segments_with_issues?: number;
    issues_by_code?: Record<string, number>;
    issues_by_severity?: Record<string, number>;
    ai?: { mode?: AiMode; checked?: number; failed?: number; units?: string };
    consistency?: { inconsistent_translations: number; inconsistent_sources: number };
    scorecard?: LqaCard;
    notes?: { unaligned_target_sentences?: number };
  };
  error: string | null;
  created_at: ISODate | null;
  finished_at: ISODate | null;
}

export interface AuditSegmentRow {
  id: string;
  seq: number;
  ref: string;
  source_tagged: string;
  target_tagged: string;
  word_count: number;
  issues: AuditIssue[];
  mqm_errors: { dimension: string; severity: MqmSeverity; span: string; explanation: string }[];
  ai_checked: boolean;
  score: number | null;
  max_severity: "none" | MqmSeverity;
  dimensions: string[];
}

export interface AuditSegmentPage extends ListResponse<AuditSegmentRow> {
  total: number;
}

export interface AuditSegmentQuery {
  severity?: string;
  min_severity?: string;
  dimension?: string;
  code?: string;
  with_issues?: boolean;
  offset?: number;
  limit?: number;
}
