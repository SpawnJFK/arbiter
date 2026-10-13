"use client";

import { useI18n } from "@/lib/i18n/client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PlanCard } from "@/components/plan-card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Stat } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { Callout, EmptyState, Progress } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import { MODULE_LABEL, UNIT_LABEL, planCurrencies, ratio } from "@/lib/billing";
import type { BillingInterval, BillingOverview, CreditWallet, Invoice, PlansResponse, Usage } from "@/lib/types";

export function Billing({
  usage,
  invoices,
  period,
  overview,
  plans,
  wallet,
  canManage,
  notice,
  highlightInvoice,
}: {
  usage: Usage;
  invoices: Invoice[];
  period: string;
  overview: BillingOverview;
  plans: PlansResponse;
  wallet: CreditWallet;
  canManage: boolean;
  notice: "success" | "cancelled" | null;
  highlightInvoice: string | null;
}) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const sub = overview.subscription;
  const [interval, setBillingInterval] = useState<BillingInterval>(sub?.interval ?? "month");
  const currencies = planCurrencies(plans.items, overview.currency);
  const [currency, setCurrency] = useState(currencies.includes(overview.currency) ? overview.currency : currencies[0]);
  const [busy, setBusy] = useState<string | null>(null);

  async function go(key: string, fn: () => Promise<{ url: string }>) {
    setBusy(key);
    try {
      const { url } = await fn();
      window.location.assign(url);
    } catch (err) {
      toast.error(t("app.settings.billing.couldNotStart"), errorMessage(err));
      setBusy(null);
    }
  }

  async function cancel() {
    if (!window.confirm(t("app.settings.billing.cancelConfirm"))) return;
    setBusy("cancel");
    try {
      await api.cancelSubscription(false);
      toast.success(t("app.settings.billing.cancelRequested"));
      router.refresh();
    } catch (err) {
      toast.error(t("app.settings.billing.couldNotCancel"), errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function openDocument(inv: Invoice) {
    if (inv.provider === "internal") {
      window.open(api.invoicePdfUrl(inv.id), "_blank", "noopener");
      return;
    }
    try {
      const { url } = await api.invoiceDocument(inv.id);
      window.open(url, "_blank", "noopener");
    } catch (err) {
      toast.error(t("app.settings.billing.documentUnavailable"), errorMessage(err));
    }
  }

  const managedAtProvider = sub && (sub.provider === "paddle" || sub.provider === "stripe");

  return (
    <div className="space-y-4">
      {notice === "success" && <Callout tone="ok">{t("app.settings.billing.checkoutSuccess")}</Callout>}
      {notice === "cancelled" && <Callout tone="warn">{t("app.settings.billing.checkoutCancelled")}</Callout>}
      {overview.pending && !sub && (
        <Callout tone="info" title={t("app.settings.billing.pendingTitle")}>
          {t("app.settings.billing.pendingBody", { plan: overview.pending.plan })}
        </Callout>
      )}
      {!canManage && <Callout tone="info">{t("app.settings.billing.readOnly")}</Callout>}

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader
            title={t("app.settings.billing.currentPlan")}
            description={sub ? t("app.settings.billing.billedBy", { provider: t.enumLabel(sub.provider) }) : t("app.settings.billing.noPlanYet")}
            actions={
              canManage && sub ? (
                <>
                  <Button size="sm" loading={busy === "portal"} onClick={() => go("portal", () => api.billingPortal())}>
                    {managedAtProvider ? t("app.settings.billing.managePayment") : t("app.settings.billing.viewBilling")}
                  </Button>
                  {!sub.cancel_at && (
                    <Button size="sm" variant="ghost" loading={busy === "cancel"} onClick={cancel}>
                      {t("app.settings.billing.cancel")}
                    </Button>
                  )}
                </>
              ) : null
            }
          />
          <CardBody>
            {sub && overview.plan ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-semibold tracking-tight">{overview.plan.name}</span>
                  <StatusBadge status={sub.status} />
                  <Badge>{sub.interval === "year" ? t("app.settings.billing.yearly") : t("app.settings.billing.monthly")}</Badge>
                </div>
                <dl className="grid gap-3 text-[13px] sm:grid-cols-3">
                  <div>
                    <dt className="text-muted">{t("app.settings.billing.seats")}</dt>
                    <dd className="tabular font-medium">{t("app.settings.billing.seatsUsed", { used: overview.seats_used, total: sub.seats })}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">{sub.cancel_at ? t("app.settings.billing.endsOn") : t("app.settings.billing.renewsOn")}</dt>
                    <dd className="font-medium">
                      <Time iso={sub.cancel_at ?? sub.current_period_end} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted">{t("app.settings.billing.platformFee")}</dt>
                    <dd className="tabular font-medium">{t("app.settings.billing.platformFeeValue", { percent: overview.platform_fee_percent })}</dd>
                  </div>
                </dl>
                <div className="flex flex-wrap gap-1.5" aria-label={t("billing.plan.modules")}>
                  {overview.modules.map((m) => (
                    <Badge key={m} tone="ok">
                      {t(MODULE_LABEL[m])}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-[13.5px] text-muted">{t("app.settings.billing.choosePlanBelow")}</p>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title={t("app.settings.billing.credits")} description={t("app.settings.billing.creditsHelp")} />
          <CardBody className="space-y-4">
            <div className="tabular text-2xl font-semibold">{f.money(wallet.balance, wallet.currency)}</div>
            {wallet.lots.length > 0 && (
              <ul className="space-y-1 text-[12.5px] text-muted">
                {wallet.lots.map((l) => (
                  <li key={l.id} className="flex justify-between gap-2">
                    <span>
                      {t.enumLabel(l.kind)} · {f.money(l.remaining, l.currency)}
                    </span>
                    <span>
                      {t("app.settings.billing.expires")} <Time iso={l.expires_at} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {canManage && (
              <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
                {wallet.packs.map((p) => (
                  <Button key={p.key} size="sm" loading={busy === `pack:${p.key}`} onClick={() => go(`pack:${p.key}`, () => api.creditCheckout(p.key))}>
                    {t("app.settings.billing.buyPack", { credit: f.money(p.credit_amount, p.currency), price: f.money(p.price, p.currency) })}
                  </Button>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader
          title={t("app.settings.billing.usage")}
          description={t("app.settings.billing.usageHelp")}
          actions={
            <div className="flex items-center gap-2">
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
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            {overview.meters.map((m) => (
              <div key={m.unit}>
                <div className="mb-1 flex justify-between gap-2 text-[13px]">
                  <span className="font-medium">{t(UNIT_LABEL[m.unit])}</span>
                  <span className="tabular text-muted">
                    {sub ? t("app.settings.billing.meterOf", { used: f.num(Number(m.used)), included: f.num(Number(m.included)) }) : f.num(Number(m.used))}
                  </span>
                </div>
                <Progress value={ratio(m.used, m.included)} tone={Number(m.overage) > 0 ? "danger" : "accent"} />
                {Number(m.overage) > 0 && (
                  <p className="mt-1 text-[12.5px] text-danger">{t("app.settings.billing.overageNote", { amount: f.num(Number(m.overage)) })}</p>
                )}
              </div>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t("app.settings.billing.billing.words")} value={f.num(usage.words)} />
            <Stat label={t("app.settings.billing.billing.aiUnits")} value={f.num(Number(usage.ai_units))} hint={t("app.settings.billing.billing.engineQeAndSenateCalls")} />
            <Stat label={t("app.settings.billing.billing.reviewDecisions")} value={f.num(usage.review_decisions)} hint={t("app.settings.billing.billing.humanDecisionsBilled")} />
            <Stat tone="accent" label={t("app.settings.billing.billing.amount")} value={f.money(usage.amount)} hint={t("app.settings.billing.feeIncluded", { fee: f.money(usage.platform_fee ?? "0") })} />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("app.settings.billing.plans")}
          description={t("app.settings.billing.plansHelp", { percent: plans.platform_fee.default_percent })}
          actions={
            <div className="flex items-center gap-2">
              <div role="group" aria-label={t("app.settings.billing.interval")} className="inline-flex rounded-md border border-border-strong p-0.5">
                {(["month", "year"] as const).map((iv) => (
                  <button
                    key={iv}
                    type="button"
                    aria-pressed={interval === iv}
                    onClick={() => setBillingInterval(iv)}
                    className={`rounded px-2.5 py-1 text-[12.5px] font-medium ${interval === iv ? "bg-accent text-accent-fg" : "text-muted hover:text-fg"}`}
                  >
                    {iv === "year" ? t("app.settings.billing.yearly") : t("app.settings.billing.monthly")}
                  </button>
                ))}
              </div>
              {currencies.length > 1 && (
                <Select aria-label={t("app.settings.billing.currency")} className="w-24" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  {currencies.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          }
        />
        <CardBody>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {plans.items.map((p) => {
              const current = sub?.plan === p.key;
              return (
                <PlanCard
                  key={p.key}
                  plan={p}
                  interval={interval}
                  currency={currency}
                  current={current}
                  action={
                    p.custom ? (
                      <p className="text-[12.5px] text-muted">{t("app.settings.billing.contractNote")}</p>
                    ) : canManage && !current ? (
                      <Button
                        variant="primary"
                        className="w-full"
                        loading={busy === `plan:${p.key}`}
                        disabled={!p.prices?.[interval]?.[currency]}
                        onClick={() => go(`plan:${p.key}`, () => api.checkout({ plan: p.key, interval, currency }))}
                      >
                        {sub ? t("app.settings.billing.switchTo", { plan: p.name }) : t("app.settings.billing.choose", { plan: p.name })}
                      </Button>
                    ) : null
                  }
                />
              );
            })}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("app.settings.billing.billing.invoices")} description={t("app.settings.billing.invoicesHelp")} />
        {invoices.length === 0 ? (
          <EmptyState title={t("app.settings.billing.billing.noInvoicesYet")} description={t("app.settings.billing.billing.invoicesAppearHereOnceThey")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.settings.billing.billing.invoice")}</Th>
                <Th className="hidden md:table-cell">{t("app.settings.billing.kind")}</Th>
                <Th className="hidden sm:table-cell">{t("app.settings.billing.billing.issued")}</Th>
                <Th className="hidden md:table-cell">{t("app.settings.billing.issuedBy")}</Th>
                <Th className="text-right">{t("app.settings.billing.billing.amount")}</Th>
                <Th>{t("app.settings.billing.billing.status")}</Th>
                <Th className="text-right">
                  <span className="sr-only">{t("app.settings.billing.document")}</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {invoices.map((i) => (
                <Tr key={i.id} className={highlightInvoice === i.id ? "bg-accent-subtle/40" : undefined}>
                  <Td className="font-mono text-[12.5px]">
                    {i.provider_invoice_number ?? i.number ?? i.id}
                    {i.due_at && i.status === "issued" && (
                      <div className="font-sans text-[12px] text-muted">
                        {t("app.settings.billing.due")} <Time iso={i.due_at} />
                      </div>
                    )}
                  </Td>
                  <Td className="hidden md:table-cell">{t.enumLabel(i.kind ?? "usage")}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={i.issued_at} />
                  </Td>
                  <Td className="hidden md:table-cell">{i.issued_by === "us" || !i.issued_by ? t("app.settings.billing.issuedByUs") : t.enumLabel(i.issued_by)}</Td>
                  <Td className="tabular text-right font-medium">
                    {f.money(i.total, i.currency ?? "EUR")}
                    {i.subtotal && i.tax && Number(i.tax) > 0 && (
                      <div className="text-[12px] font-normal text-faint">
                        {f.money(i.subtotal, i.currency ?? "EUR")} {t("app.settings.billing.billing.tax")} {f.money(i.tax, i.currency ?? "EUR")}
                      </div>
                    )}
                  </Td>
                  <Td>
                    <StatusBadge status={i.status} />
                  </Td>
                  <Td className="text-right">
                    {i.document_url &&
                      (i.provider === "internal" ? (
                        <AnchorButton size="sm" variant="ghost" href={api.invoicePdfUrl(i.id)}>
                          {t("app.settings.billing.pdf")}
                        </AnchorButton>
                      ) : (
                        <Button size="sm" variant="ghost" onClick={() => openDocument(i)}>
                          {t("app.settings.billing.viewDocument")}
                        </Button>
                      ))}
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
