import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { ReviewersTable } from "./reviewers-table";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.reviewers") };
}

const STATUSES = ["applied", "active", "suspended", "banned"];

export default async function AdminReviewersPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { t } = await getI18n();
  const { status } = await searchParams;
  const s = status && STATUSES.includes(status) ? status : "";
  const { items } = await withAuth((api) => api.adminReviewers({ status: s || undefined, limit: 200 }), "/admin");
  return (
    <>
      <PageHeader title={t("admin.reviewers")} description={t("admin.applicantsBecomeActiveWhenThey")} />
      <ReviewersTable key={s} initial={items} status={s} statuses={STATUSES} />
    </>
  );
}
