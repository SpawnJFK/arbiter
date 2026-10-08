import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { DisputesList } from "./disputes-list";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.disputes.disputes") };
}

export default async function AdminDisputesPage() {
  const { t } = await getI18n();
  const { items } = await withAuth((api) => api.adminDisputes({ limit: 200 }), "/admin/disputes");
  return (
    <>
      <PageHeader title={t("admin.disputes.disputes")} description={t("admin.disputes.reviewerDisputesAboutScoresControl")} />
      <DisputesList initial={items} />
    </>
  );
}
