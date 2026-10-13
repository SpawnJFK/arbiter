"use client";

import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n/client";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { MODULE_KEYS, MODULE_LABEL, UNIT_LABEL, planPrice } from "@/lib/billing";
import type { BillingInterval, Plan } from "@/lib/types";

/** One plan as sold: modules, price for the chosen interval and currency, included volume, overage. */
export function PlanCard({
  plan,
  interval,
  currency,
  current,
  action,
}: {
  plan: Plan;
  interval: BillingInterval;
  currency: string;
  current?: boolean;
  action?: ReactNode;
}) {
  const { f, t } = useI18n();
  const price = planPrice(plan, interval, currency);
  const over = plan.overage?.[currency] ?? {};
  return (
    <div
      className={cn(
        "flex flex-col rounded-lg border bg-surface p-4 shadow-card",
        current ? "border-accent ring-1 ring-accent/30" : "border-border",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold tracking-tight text-fg">{plan.name}</h3>
        {current && <Badge tone="accent">{t("billing.plan.current")}</Badge>}
      </div>
      <p className="mt-1 min-h-10 text-[13px] text-muted">{plan.description}</p>
      <div className="mt-3">
        {plan.custom ? (
          <div className="text-lg font-semibold text-fg">{t("billing.plan.contract")}</div>
        ) : price ? (
          <div className="flex items-baseline gap-1">
            <span className="tabular text-2xl font-semibold text-fg">{f.money(price, currency)}</span>
            <span className="text-[13px] text-muted">{interval === "year" ? t("billing.plan.perYear") : t("billing.plan.perMonth")}</span>
          </div>
        ) : (
          <div className="text-[13px] text-muted">{t("billing.plan.notInCurrency", { currency })}</div>
        )}
        <div className="mt-0.5 text-[12.5px] text-muted">
          {t("billing.plan.seatsIncluded", { count: plan.seats_included })}
        </div>
      </div>
      <ul className="mt-4 space-y-1.5 text-[13px]" aria-label={t("billing.plan.modules")}>
        {MODULE_KEYS.map((m) => {
          const on = plan.modules.includes(m);
          return (
            <li key={m} className={cn("flex items-center gap-2", on ? "text-fg" : "text-faint line-through decoration-faint/50")}>
              <span aria-hidden="true" className={cn("size-1.5 rounded-full", on ? "bg-ok" : "bg-border-strong")} />
              <span>{t(MODULE_LABEL[m])}</span>
              <span className="sr-only">{on ? t("billing.plan.included") : t("billing.plan.notIncluded")}</span>
            </li>
          );
        })}
      </ul>
      {!plan.custom && (
        <dl className="mt-4 space-y-1 border-t border-border pt-3 text-[12.5px] text-muted">
          {(["word", "ai_unit"] as const).map((u) =>
            plan.included?.[u] ? (
              <div key={u} className="flex justify-between gap-2">
                <dt>{t(UNIT_LABEL[u])}</dt>
                <dd className="tabular text-right text-fg">
                  {t("billing.plan.includedPerMonth", { amount: f.num(Number(plan.included[u])) })}
                  {over[u] && <span className="block text-muted">{t("billing.plan.thenPer", { rate: `${f.num(Number(over[u]), 4)} ${currency}` })}</span>}
                </dd>
              </div>
            ) : null,
          )}
        </dl>
      )}
      {action && <div className="mt-4 pt-1">{action}</div>}
    </div>
  );
}
