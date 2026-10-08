"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { StatusBadge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import type { Invoice, Usage } from "@/lib/types";

export function Billing({ usage, invoices, period }: { usage: Usage; invoices: Invoice[]; period: string }) {
  const { f, t } = useI18n();
  const router = useRouter();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="period" className="text-[13px] font-medium">
          {t("app.settings.billing.billing.period")}
        </label>
        <Input
          id="period"
          type="month"
          className="w-44"
          value={period}
          onChange={(e) => e.target.value && router.push(`/app/settings/billing?period=${e.target.value}`)}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("app.settings.billing.billing.words")} value={f.num(usage.words)} />
        <Stat label={t("app.settings.billing.billing.aiUnits")} value={f.num(Number(usage.ai_units))} hint={t("app.settings.billing.billing.engineQeAndSenateCalls")} />
        <Stat label={t("app.settings.billing.billing.reviewDecisions")} value={f.num(usage.review_decisions)} hint={t("app.settings.billing.billing.humanDecisionsBilled")} />
        <Stat tone="accent" label={t("app.settings.billing.billing.amount")} value={f.money(usage.amount)} hint={t("app.settings.billing.billing.period2", { period: usage.period })} />
      </div>
      <Card>
        <CardHeader title={t("app.settings.billing.billing.invoices")} />
        {invoices.length === 0 ? (
          <EmptyState title={t("app.settings.billing.billing.noInvoicesYet")} description={t("app.settings.billing.billing.invoicesAppearHereOnceThey")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.settings.billing.billing.invoice")}</Th>
                <Th>{t("app.settings.billing.billing.period")}</Th>
                <Th className="hidden sm:table-cell">{t("app.settings.billing.billing.issued")}</Th>
                <Th className="text-right">{t("app.settings.billing.billing.amount")}</Th>
                <Th>{t("app.settings.billing.billing.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("app.settings.billing.billing.breakdown")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {invoices.map((i) => (
                <Tr key={i.id}>
                  <Td className="font-mono text-[12.5px]">{i.number ?? i.id}</Td>
                  <Td>{i.period ?? "–"}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={i.issued_at} />
                  </Td>
                  <Td className="tabular text-right font-medium">{f.money(i.total, i.currency ?? "EUR")}</Td>
                  <Td>
                    <StatusBadge status={i.status} />
                  </Td>
                  <Td className="text-right">
                    {i.subtotal && i.tax && Number(i.tax) > 0 && (
                      <span className="text-[12px] text-faint">
                        {f.money(i.subtotal, i.currency ?? "EUR")} {t("app.settings.billing.billing.tax")} {f.money(i.tax, i.currency ?? "EUR")}
                      </span>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
