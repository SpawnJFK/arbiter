// Shared billing helpers for the billing page, the public pricing page and the admin editor.
import { k } from "@/lib/i18n/core";
import type { BillingInterval, ModuleKey, Plan } from "./types";

/** platform/modules.py MODULES, in the same order. */
export const MODULE_KEYS: ModuleKey[] = ["tms", "engine", "ai", "pm", "auditor", "strings", "community"];

export const MODULE_LABEL: Record<ModuleKey, string> = {
  tms: k("billing.module.tms"),
  engine: k("billing.module.engine"),
  ai: k("billing.module.ai"),
  pm: k("billing.module.pm"),
  auditor: k("billing.module.auditor"),
  strings: k("billing.module.strings"),
  community: k("billing.module.community"),
};

export const UNIT_LABEL: Record<"word" | "ai_unit", string> = {
  word: k("billing.unit.word"),
  ai_unit: k("billing.unit.aiUnit"),
};

export function planPrice(plan: Plan, interval: BillingInterval, currency: string): string | null {
  return plan.prices?.[interval]?.[currency] ?? null;
}

/** Currencies any plan is priced in, the default first when present. */
export function planCurrencies(plans: Plan[], fallback = "EUR"): string[] {
  const set = new Set<string>();
  for (const p of plans) for (const c of p.currencies) set.add(c);
  const list = [...set].sort();
  if (list.includes(fallback)) return [fallback, ...list.filter((c) => c !== fallback)];
  return list.length ? list : [fallback];
}

export function ratio(used: string, included: string): number {
  const u = Number(used);
  const i = Number(included);
  if (!i) return u > 0 ? 1 : 0;
  return Math.min(1, u / i);
}
