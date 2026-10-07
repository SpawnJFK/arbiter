import type { WidgetType } from "./types";

/** Metric catalogue from docs/api-contract.md (Agency OS, Dashboards). */
export const METRICS: Record<WidgetType, string[]> = {
  kpi: ["revenue", "margin", "margin_pct", "jobs_active", "jobs_overdue", "auto_rate", "escaped_rate", "open_deals_value", "words_delivered", "reviewer_cost"],
  bar: ["revenue_by_month", "jobs_by_state", "revenue_by_account", "words_by_pair", "auto_rate_by_month"],
  line: ["revenue_by_month", "jobs_by_state", "revenue_by_account", "words_by_pair", "auto_rate_by_month"],
  pipeline: ["deals_by_stage"],
  table: ["overdue_jobs", "top_accounts", "open_activities", "recent_deliveries"],
};

export const METRIC_LABEL: Record<string, string> = {
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

export const TYPE_LABEL: Record<WidgetType, string> = {
  kpi: "KPI tile",
  bar: "Bar chart",
  line: "Line chart",
  pipeline: "Pipeline",
  table: "Table",
};

/** Lower is better for these KPIs (delta colouring). */
export const LOWER_IS_BETTER = new Set(["jobs_overdue", "escaped_rate", "reviewer_cost"]);
