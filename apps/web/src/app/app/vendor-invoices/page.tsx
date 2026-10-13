import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { InvoicesManager } from "./invoices-manager";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.vendorInvoices.vendorInvoices") };
}

function currentPeriod(): string {
  return new Date().toISOString().slice(0, 7);
}

export default async function VendorInvoicesPage({ searchParams }: { searchParams: Promise<{ period?: string }> }) {
  const { t } = await getI18n();
  const sp = await searchParams;
  const period = /^\d{4}-\d{2}$/.test(sp.period ?? "") ? (sp.period as string) : currentPeriod();
  const [invoices, payables, approved] = await withAuth(
    (api) =>
      Promise.all([
        api.vendorInvoices({ period, limit: 200 }),
        api.payables(period),
        api.assignments({ status: "approved", limit: 200 }),
      ]),
    "/app/vendor-invoices",
  );
  return (
    <>
      <PageHeader title={t("app.vendorInvoices.vendorInvoices")} description={t("app.vendorInvoices.description")} />
      <InvoicesManager period={period} invoices={invoices.items} payables={payables} approvedCount={approved.items.length} />
    </>
  );
}
