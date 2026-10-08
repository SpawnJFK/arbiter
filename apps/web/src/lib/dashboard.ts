import type { Translator } from "./i18n/core";
import type { WidgetType } from "./types";

/** Metric catalogue from docs/api-contract.md (Agency OS, Dashboards). */
export const METRICS: Record<WidgetType, string[]> = {
  kpi: ["revenue", "margin", "margin_pct", "jobs_active", "jobs_overdue", "auto_rate", "escaped_rate", "open_deals_value", "words_delivered", "reviewer_cost"],
  bar: ["revenue_by_month", "jobs_by_state", "revenue_by_account", "words_by_pair", "auto_rate_by_month"],
  line: ["revenue_by_month", "jobs_by_state", "revenue_by_account", "words_by_pair", "auto_rate_by_month"],
  pipeline: ["deals_by_stage"],
  table: ["overdue_jobs", "top_accounts", "open_activities", "recent_deliveries"],
};

/** Label for a metric id (`metric.<id>` in messages/en.json), falling back to the id. */
export function metricLabel(t: Translator, metric: string): string {
  const key = `metric.${metric}`;
  return t.has(key) ? t(key) : metric;
}

export function widgetTypeLabel(t: Translator, type: WidgetType): string {
  return t(`widgetType.${type}`);
}

/** Lower is better for these KPIs (delta colouring). */
export const LOWER_IS_BETTER = new Set(["jobs_overdue", "escaped_rate", "reviewer_cost"]);
