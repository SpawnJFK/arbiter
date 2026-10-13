import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { PayoutMethods } from "./payout-methods";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.payouts.title") };
}

export default async function PayoutMethodsPage() {
  const { t } = await getI18n();
  const view = await withAuth((api) => api.payoutMethods(), "/reviewer/payouts");
  return (
    <>
      <PageHeader title={t("reviewer.payouts.title")} description={t("reviewer.payouts.description")} />
      <PayoutMethods view={view} />
    </>
  );
}
