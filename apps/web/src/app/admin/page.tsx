import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { ReviewersTable } from "./reviewers-table";

export const metadata: Metadata = { title: "Reviewers" };

const STATUSES = ["applied", "active", "suspended", "banned"];

export default async function AdminReviewersPage({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const { status } = await searchParams;
  const s = status && STATUSES.includes(status) ? status : "";
  const { items } = await withAuth((api) => api.adminReviewers({ status: s || undefined, limit: 200 }), "/admin");
  return (
    <>
      <PageHeader title="Reviewers" description="Applicants become active when they pass the tests for a pair. Approve manually, set levels, suspend or ban." />
      <ReviewersTable key={s} initial={items} status={s} statuses={STATUSES} />
    </>
  );
}
