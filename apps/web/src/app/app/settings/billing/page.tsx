import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { withAuth } from "@/lib/server-api";
import { Billing } from "./billing";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.settings.billing.metaTitle") };
}

export default async function BillingPage({ searchParams }: { searchParams: Promise<{ period?: string }> }) {
  const { period: p } = await searchParams;
  const period = p && /^\d{4}-\d{2}$/.test(p) ? p : new Date().toISOString().slice(0, 7);
  const [usage, invoices] = await withAuth((api) => Promise.all([api.usage(period), api.invoices({ limit: 50 })]), "/app/settings/billing");
  return <Billing usage={usage} invoices={invoices.items} period={period} />;
}
