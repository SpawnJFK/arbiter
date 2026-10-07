import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { ReviewersTable } from "./reviewers-table";

export const metadata: Metadata = { title: "Reviewers" };

const STATUSES = ["applied", "testing", "active", "suspended", "rejected"];

export default async function AdminReviewersPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const s = status && STATUSES.includes(status) ? status : "";
  const { items } = await withAuth((api) => api.adminReviewers({ status: s || undefined, limit: 200 }), "/admin");
  return (
    <>
      <PageHeader title="Reviewers" description="Approve applicants after their tests, set levels, and suspend reviewers whose control-sample agreement drops." />
      <ReviewersTable key={s} initial={items} status={s} statuses={STATUSES} />
    </>
  );
}
