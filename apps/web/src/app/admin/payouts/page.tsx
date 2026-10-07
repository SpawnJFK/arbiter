import type { Metadata } from "next";
import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { money } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import { RunPayoutsButton } from "./run-button";

export const metadata: Metadata = { title: "Payouts" };

export default async function PayoutsPage() {
  const { items } = await withAuth((api) => api.adminPayouts({ limit: 200 }), "/admin/payouts");
  return (
    <>
      <PageHeader
        title="Payouts"
        description="A run pays every reviewer whose available balance is above their threshold and whose tax details are complete."
        actions={<RunPayoutsButton />}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="No payouts yet" />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Payout</Th>
                <Th>Reviewer</Th>
                <Th className="text-right">Amount</Th>
                <Th>State</Th>
                <Th className="hidden sm:table-cell">Created</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((p) => (
                <Tr key={p.id}>
                  <Td className="font-mono text-[12.5px]">{p.id}</Td>
                  <Td className="font-mono text-[12.5px] text-muted">{p.reviewer_id}</Td>
                  <Td className="tabular text-right font-medium">{money(p.amount)}</Td>
                  <Td>
                    <StatusBadge status={p.state} />
                  </Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={p.created_at} />
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
