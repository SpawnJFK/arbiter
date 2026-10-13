import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { getMe, withAuth } from "@/lib/server-api";
import { Billing } from "./billing";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.settings.billing.metaTitle") };
}

export default async function BillingPage({
  searchParams,
}: {
  searchParams: Promise<{ period?: string; checkout?: string; credits?: string; invoice?: string }>;
}) {
  const sp = await searchParams;
  const period = sp.period && /^\d{4}-\d{2}$/.test(sp.period) ? sp.period : new Date().toISOString().slice(0, 7);
  const [{ user }, [usage, invoices, overview, plans, wallet]] = await Promise.all([
    getMe(),
    withAuth(
      (api) => Promise.all([api.usage(period), api.invoices({ limit: 50 }), api.billing(), api.plans(), api.credits()]),
      "/app/settings/billing",
    ),
  ]);
  const notice = sp.checkout === "success" || sp.credits === "success" ? "success" : sp.checkout === "cancelled" || sp.credits === "cancelled" ? "cancelled" : null;
  return (
    <Billing
      usage={usage}
      invoices={invoices.items}
      period={period}
      overview={overview}
      plans={plans}
      wallet={wallet}
      canManage={user.role === "pm"}
      notice={notice}
      highlightInvoice={sp.invoice ?? null}
    />
  );
}
