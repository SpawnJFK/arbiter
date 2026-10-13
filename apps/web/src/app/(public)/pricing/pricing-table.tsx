"use client";

import { useI18n } from "@/lib/i18n/client";
import { useState } from "react";
import { PlanCard } from "@/components/plan-card";
import { ButtonLink } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { planCurrencies } from "@/lib/billing";
import type { BillingInterval, PlansResponse } from "@/lib/types";

export function PricingTable({ plans }: { plans: PlansResponse }) {
  const { f, t } = useI18n();
  const currencies = planCurrencies(plans.items);
  const [interval, setBillingInterval] = useState<BillingInterval>("month");
  const [currency, setCurrency] = useState(currencies[0]);
  return (
    <>
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <div role="group" aria-label={t("pricing.interval")} className="inline-flex rounded-md border border-border-strong p-0.5">
          {(["month", "year"] as const).map((iv) => (
            <button
              key={iv}
              type="button"
              aria-pressed={interval === iv}
              onClick={() => setBillingInterval(iv)}
              className={`rounded px-3 py-1 text-[13px] font-medium ${interval === iv ? "bg-accent text-accent-fg" : "text-muted hover:text-fg"}`}
            >
              {iv === "year" ? t("pricing.yearly") : t("pricing.monthly")}
            </button>
          ))}
        </div>
        {currencies.length > 1 && (
          <Select aria-label={t("pricing.currency")} className="w-24" value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )}
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {plans.items.map((p) => (
          <PlanCard
            key={p.key}
            plan={p}
            interval={interval}
            currency={currency}
            action={
              p.custom ? (
                <p className="text-[12.5px] text-muted">{t("pricing.contractNote")}</p>
              ) : (
                <ButtonLink href="/register" variant="primary" className="w-full">
                  {t("pricing.start", { plan: p.name })}
                </ButtonLink>
              )
            }
          />
        ))}
      </div>

      <section className="mt-12 grid gap-8 border-t border-border pt-10 md:grid-cols-3" aria-labelledby="how-billing">
        <h2 id="how-billing" className="text-lg font-semibold tracking-tight md:col-span-3">
          {t("pricing.howTitle")}
        </h2>
        <div>
          <h3 className="text-[14px] font-semibold">{t("pricing.feeTitle")}</h3>
          <p className="mt-1 text-[13.5px] text-muted">
            {t("pricing.feeBody", { percent: plans.platform_fee.default_percent, max: plans.platform_fee.max_percent })}
          </p>
        </div>
        <div>
          <h3 className="text-[14px] font-semibold">{t("pricing.overageTitle")}</h3>
          <p className="mt-1 text-[13.5px] text-muted">{t("pricing.overageBody")}</p>
        </div>
        <div>
          <h3 className="text-[14px] font-semibold">{t("pricing.taxTitle")}</h3>
          <p className="mt-1 text-[13.5px] text-muted">{t("pricing.taxBody")}</p>
        </div>
        {plans.credit_packs.length > 0 && (
          <div className="md:col-span-3">
            <h3 className="text-[14px] font-semibold">{t("pricing.creditsTitle")}</h3>
            <ul className="mt-2 flex flex-wrap gap-2 text-[13px]">
              {plans.credit_packs.map((c) => (
                <li key={c.key} className="rounded-md border border-border bg-surface px-3 py-1.5">
                  {t("pricing.pack", { credit: f.money(c.credit_amount, c.currency), price: f.money(c.price, c.currency), days: c.valid_days })}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </>
  );
}
