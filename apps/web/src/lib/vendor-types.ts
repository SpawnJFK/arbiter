// Vendor management (module pm): routes/vendors.py and routes/vendor_portal.py.
import type { FlaggedError, ISODate, Money } from "./types";

export type VendorService = "translation" | "review" | "post-edit" | "dtp";
export const VENDOR_SERVICES: VendorService[] = ["translation", "review", "post-edit", "dtp"];
export type RateUnit = "word" | "hour" | "page" | "minimum";
export const RATE_UNITS: RateUnit[] = ["word", "hour", "page", "minimum"];
export type VendorStatus = "active" | "inactive" | "blocked";
export type HumanStep = "human_review" | "second_review";
export type AssignmentStatus =
  | "pending"
  | "offered"
  | "accepted"
  | "declined"
  | "expired"
  | "withdrawn"
  | "in_progress"
  | "delivered"
  | "approved"
  | "invoiced"
  | "cancelled";

export interface VendorPair {
  source_lang: string;
  target_lang: string;
  services: VendorService[];
}

export interface VendorRate {
  source_lang: string | null;
  target_lang: string | null;
  service: VendorService;
  unit: RateUnit;
  rate: string;
  currency: string;
}

export interface VendorAbsence {
  id: string;
  vendor_id: string;
  start_date: string;
  end_date: string;
  note: string;
}

export interface VendorDocument {
  id: string;
  vendor_id: string;
  kind: "nda" | "contract" | "certificate" | "other";
  title: string;
  signed: boolean;
  signed_at: string | null;
  valid_until: string | null;
}

export interface Vendor {
  id: string;
  kind: "person" | "company";
  name: string;
  email: string | null;
  phone: string | null;
  country: string | null;
  status: VendorStatus;
  pairs: VendorPair[];
  domains: string[];
  rates: VendorRate[];
  currency: string;
  rating: string | null;
  notes: string;
  legal_name: string | null;
  tax_id: string | null;
  address: string | null;
  payment_method: string | null;
  iban: string | null;
  swift: string | null;
  payment_terms_days: number;
  capacity_words_per_day: number;
  working_days: number[];
  nda_signed: boolean;
  nda_signed_at: string | null;
  open_assignments?: number;
  absences?: VendorAbsence[];
  documents?: VendorDocument[];
  assignments?: VendorAssignment[];
  created_at: ISODate;
}

export interface VendorInput {
  name: string;
  kind?: "person" | "company";
  email?: string | null;
  phone?: string | null;
  country?: string | null;
  status?: VendorStatus;
  pairs?: VendorPair[];
  domains?: string[];
  rates?: Array<Omit<VendorRate, "currency"> & { currency?: string }>;
  currency?: string;
  rating?: string | null;
  notes?: string;
  legal_name?: string | null;
  tax_id?: string | null;
  address?: string | null;
  iban?: string | null;
  swift?: string | null;
  payment_terms_days?: number;
  capacity_words_per_day?: number;
  working_days?: number[];
  nda_signed?: boolean;
}

export interface VendorAssignment {
  id: string;
  job_id: string;
  step: HumanStep;
  service: VendorService;
  assignee_kind: "vendor" | "internal";
  vendor_id: string | null;
  vendor_name: string | null;
  user_id: string | null;
  user_name: string | null;
  rank: number;
  strategy: "sequential" | "broadcast";
  words: number;
  words_done: number;
  unit: RateUnit;
  rate: string;
  amount: Money;
  currency: string;
  status: AssignmentStatus;
  due_at: ISODate | null;
  offered_at: ISODate | null;
  offer_expires_at: ISODate | null;
  delivered_at: ISODate | null;
  approved_at: ISODate | null;
  po_id: string | null;
  po_number: string | null;
  link?: string;
  created_at: ISODate;
}

export interface JobAssignments {
  job_id: string;
  routes: Partial<Record<HumanStep, { mode: "marketplace" | "vendor" | "internal"; assignment_id: string | null; status: string | null }>>;
  items: VendorAssignment[];
}

export interface CapacityRow {
  vendor_id: string;
  name: string;
  capacity_words_per_day: number;
  free_words: number;
  earliest_finish: string | null;
  can_meet: boolean;
  absent_days: string[];
  price: { amount: Money; rate: string; unit: string; currency: string } | null;
  rating: string | null;
  nda_signed: boolean;
  eligible: boolean;
  rank: number;
}

export interface Suggestions {
  job_id: string;
  step: HumanStep;
  words: number;
  due_at: ISODate | null;
  items: CapacityRow[];
}

export interface AssignmentInput {
  step: HumanStep;
  mode: "marketplace" | "vendor" | "internal";
  vendor_ids?: string[];
  user_id?: string;
  strategy?: "sequential" | "broadcast";
  offer_timeout_minutes?: number;
}

export interface PurchaseOrder {
  id: string;
  number: string;
  vendor_id: string;
  vendor_name: string | null;
  assignment_id: string;
  job_id: string;
  total: Money;
  currency: string;
  status: "issued" | "invoiced" | "cancelled";
  due_at: ISODate | null;
  issued_at: ISODate;
}

export interface VendorInvoice {
  id: string;
  vendor_id: string;
  vendor_name: string | null;
  number: string;
  source: "auto" | "upload";
  period: string;
  assignment_ids: string[];
  total: Money;
  currency: string;
  status: "received" | "approved" | "rejected" | "paid";
  has_file: boolean;
  due_date: string | null;
  received_at: ISODate;
  paid_at: ISODate | null;
}

export interface PayableRow {
  vendor_id: string;
  vendor_name: string | null;
  currency: string;
  accrued: Money;
  invoiced: Money;
  paid: Money;
  open: Money;
}

export interface Payables {
  period: string;
  items: PayableRow[];
  totals: Omit<PayableRow, "vendor_id" | "vendor_name">[];
}

export interface RiskRow {
  job_id: string;
  project: string | null;
  source_lang: string;
  target_lang: string;
  due_at: ISODate;
  remaining_words: number;
  estimated_finish: ISODate;
  slack_hours: number;
  at_risk: boolean;
  reasons: string[];
  routes: Record<string, { route: string; words: number; vendor_name?: string }>;
}

export interface TimelineDay {
  date: string;
  capacity: number;
  load: number;
  free: number;
  absent: boolean;
  working: boolean;
  assignments: string[];
}

export interface Timeline {
  start: string;
  days: string[];
  vendors: { vendor_id: string; name: string; capacity_words_per_day: number; days: TimelineDay[] }[];
  assignments: { id: string; vendor_id: string | null; job_id: string; step: string; status: string; words: number; words_done: number; due_at: ISODate | null }[];
  jobs: { job_id: string; project: string | null; state: string; due_at: ISODate; source_lang: string; target_lang: string; at_risk: boolean }[];
}

export interface PortalSegment {
  id: string;
  seq: number;
  source_tagged: string;
  target_tagged: string | null;
  context_before: string | null;
  context_after: string | null;
  terms: { source_term: string | null; target_term: string | null; kind: string | null }[];
  qe_score: number | null;
  flagged_errors: FlaggedError[];
  word_count: number;
  state: string;
  done: boolean;
}

export interface PortalView {
  assignment: {
    id: string;
    step: HumanStep;
    service: string;
    assignee_kind: "vendor" | "internal";
    status: AssignmentStatus;
    words: number;
    words_done: number;
    rate: string;
    unit: string;
    amount: Money;
    currency: string;
    due_at: ISODate | null;
    offer_expires_at: ISODate | null;
    note: string;
    po_number: string | null;
  };
  organization: string;
  job: { id: string; source_lang: string; target_lang: string; content_type: string; state: string; segment_count: number };
  segments: PortalSegment[];
  remaining: number;
}
