import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { DisputesList } from "./disputes-list";

export const metadata: Metadata = { title: "Disputes" };

export default async function AdminDisputesPage() {
  const { items } = await withAuth((api) => api.adminDisputes({ limit: 200 }), "/admin/disputes");
  return (
    <>
      <PageHeader title="Disputes" description="Reviewer disputes about scores, control samples and ledger adjustments. Decide before the due date." />
      <DisputesList initial={items} />
    </>
  );
}
