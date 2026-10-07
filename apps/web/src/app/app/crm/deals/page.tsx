import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { DealBoard } from "./deal-board";

export const metadata: Metadata = { title: "Deals" };

export default async function DealsPage() {
  const [deals, accounts] = await withAuth((api) => Promise.all([api.deals({ limit: 200 }), api.accounts({ limit: 200 })]), "/app/crm/deals");
  return (
    <>
      <PageHeader title="Deals" description="Drag a card to another stage, or use the stage menu on the card. Totals are per column." />
      <DealBoard initial={deals.items} accounts={accounts.items} />
    </>
  );
}
