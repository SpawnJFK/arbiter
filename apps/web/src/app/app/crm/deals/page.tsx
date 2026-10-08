import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { DealBoard } from "./deal-board";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.crm.deals.deals") };
}

export default async function DealsPage() {
  const { t } = await getI18n();
  const [deals, accounts] = await withAuth((api) => Promise.all([api.deals({ limit: 200 }), api.accounts({ limit: 200 })]), "/app/crm/deals");
  return (
    <>
      <PageHeader title={t("app.crm.deals.deals")} description={t("app.crm.deals.dragACardToAnother")} />
      <DealBoard initial={deals.items} accounts={accounts.items} />
    </>
  );
}
