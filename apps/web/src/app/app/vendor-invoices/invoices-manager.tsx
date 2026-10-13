"use client";

import { useI18n } from "@/lib/i18n/client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icons } from "@/components/icons";
import { Badge, type Tone } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api, errorMessage } from "@/lib/api";
import type { Payables, VendorInvoice } from "@/lib/vendor-types";

const TONE: Record<VendorInvoice["status"], Tone> = { received: "info", approved: "accent", rejected: "danger", paid: "ok" };

export function InvoicesManager({
  period,
  invoices,
  payables,
  approvedCount,
}: {
  period: string;
  invoices: VendorInvoice[];
  payables: Payables;
  approvedCount: number;
}) {
  const { f, t } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function auto() {
    setBusy("auto");
    try {
      const r = await api.autoInvoices({});
      toast.success(t("app.vendorInvoices.generated", { count: r.items.length }));
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendorInvoices.couldNotGenerate"), errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  async function setStatus(id: string, action: "approve" | "reject" | "pay") {
    setBusy(id);
    try {
      await api.setVendorInvoiceStatus(id, action);
      router.refresh();
    } catch (e) {
      toast.error(t("app.vendorInvoices.couldNotUpdate"), errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const total = payables.totals[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[13px]">
          <span className="mb-1 block font-medium">{t("app.vendorInvoices.period")}</span>
          <Input type="month" value={period} onChange={(e) => e.target.value && router.push(`/app/vendor-invoices?period=${e.target.value}`)} className="w-40" />
        </label>
        <AnchorButton href={`/api/proxy/vendor-invoices/export.csv?period=${period}`} download>
          <Icons.download className="size-4" /> {t("app.vendorInvoices.exportCsv")}
        </AnchorButton>
        <Button variant="primary" className="ml-auto" onClick={auto} loading={busy === "auto"} disabled={approvedCount === 0}>
          {t("app.vendorInvoices.invoiceApproved", { count: approvedCount })}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={t("app.vendorInvoices.accrued")} value={total ? f.money(total.accrued, total.currency) : f.money(0)} hint={t("app.vendorInvoices.accruedHint")} tone="warn" />
        <Stat label={t("app.vendorInvoices.invoicedOpen")} value={total ? f.money(total.invoiced, total.currency) : f.money(0)} hint={t("app.vendorInvoices.invoicedOpenHint")} tone="accent" />
        <Stat label={t("app.vendorInvoices.paid")} value={total ? f.money(total.paid, total.currency) : f.money(0)} hint={t("app.vendorInvoices.paidHint")} tone="ok" />
        <Stat label={t("app.vendorInvoices.openTotal")} value={total ? f.money(total.open, total.currency) : f.money(0)} hint={f.month(period)} />
      </div>

      <Card>
        <CardHeader title={t("app.vendorInvoices.payablesByVendor", { month: f.month(period) })} />
        {payables.items.length === 0 ? (
          <EmptyState title={t("app.vendorInvoices.noPayables")} description={t("app.vendorInvoices.noPayablesHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.vendorInvoices.vendor")}</Th>
                <Th className="text-right">{t("app.vendorInvoices.accrued")}</Th>
                <Th className="text-right">{t("app.vendorInvoices.invoicedOpen")}</Th>
                <Th className="text-right">{t("app.vendorInvoices.paid")}</Th>
                <Th className="text-right">{t("app.vendorInvoices.openTotal")}</Th>
              </tr>
            </THead>
            <TBody>
              {payables.items.map((p) => (
                <Tr key={`${p.vendor_id}-${p.currency}`}>
                  <Td>
                    <Link href={`/app/vendors/${p.vendor_id}`} className="font-medium hover:text-accent hover:underline">
                      {p.vendor_name}
                    </Link>
                  </Td>
                  <Td className="tabular text-right">{f.money(p.accrued, p.currency)}</Td>
                  <Td className="tabular text-right">{f.money(p.invoiced, p.currency)}</Td>
                  <Td className="tabular text-right">{f.money(p.paid, p.currency)}</Td>
                  <Td className="tabular text-right font-medium">{f.money(p.open, p.currency)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title={t("app.vendorInvoices.invoicesOf", { month: f.month(period) })} />
        {invoices.length === 0 ? (
          <EmptyState title={t("app.vendorInvoices.noInvoices")} description={t("app.vendorInvoices.noInvoicesHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.vendorInvoices.number")}</Th>
                <Th>{t("app.vendorInvoices.vendor")}</Th>
                <Th className="hidden md:table-cell">{t("app.vendorInvoices.source")}</Th>
                <Th>{t("app.vendorInvoices.status")}</Th>
                <Th className="text-right">{t("app.vendorInvoices.total")}</Th>
                <Th className="hidden lg:table-cell">{t("app.vendorInvoices.due")}</Th>
                <Th />
              </tr>
            </THead>
            <TBody>
              {invoices.map((inv) => (
                <Tr key={inv.id}>
                  <Td className="font-mono text-[12.5px] font-medium">
                    {inv.has_file ? (
                      <a href={`/api/proxy/vendor-invoices/${encodeURIComponent(inv.id)}/file`} className="hover:text-accent hover:underline" download>
                        {inv.number}
                      </a>
                    ) : (
                      inv.number
                    )}
                  </Td>
                  <Td>{inv.vendor_name}</Td>
                  <Td className="hidden text-muted md:table-cell">{t.enumLabel(inv.source)}</Td>
                  <Td>
                    <Badge tone={TONE[inv.status]}>{t.enumLabel(inv.status)}</Badge>
                  </Td>
                  <Td className="tabular text-right">{f.money(inv.total, inv.currency)}</Td>
                  <Td className="hidden text-muted lg:table-cell">{inv.due_date ? f.dateOnly(inv.due_date) : "–"}</Td>
                  <Td className="text-right">
                    <span className="inline-flex gap-1">
                      {inv.status === "received" && (
                        <>
                          <Button size="sm" variant="primary" loading={busy === inv.id} onClick={() => setStatus(inv.id, "approve")}>
                            {t("app.vendorInvoices.approve")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setStatus(inv.id, "reject")}>
                            {t("app.vendorInvoices.reject")}
                          </Button>
                        </>
                      )}
                      {inv.status === "approved" && (
                        <Button size="sm" loading={busy === inv.id} onClick={() => setStatus(inv.id, "pay")}>
                          {t("app.vendorInvoices.markPaid")}
                        </Button>
                      )}
                    </span>
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
