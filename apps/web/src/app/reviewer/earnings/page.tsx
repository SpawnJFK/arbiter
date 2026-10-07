import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { humanize, money } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import { PayoutForm } from "./payout-form";

export const metadata: Metadata = { title: "Earnings & payouts" };

export default async function EarningsPage() {
  const [earnings, me] = await withAuth((api) => Promise.all([api.earnings(), api.reviewerMe()]), "/reviewer/earnings");
  return (
    <>
      <PageHeader title="Earnings & payouts" description="Every decision you submit is a ledger entry. Disputed entries are adjusted, never deleted." />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat tone="ok" label="Available" value={money(earnings.balance)} hint={`Paid out from ${money(me.payout_threshold)}`} />
        <Stat tone="warn" label="In payout" value={money(earnings.pending)} hint="Accrued or sent, not yet settled" />
        <Stat label="Paid to date" value={money(earnings.paid)} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader title="Ledger" />
          {earnings.entries.length === 0 ? (
            <EmptyState title="No entries yet" description="Accept, edit or escalate a task to earn your first entry." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Date</Th>
                  <Th>Entry</Th>
                  <Th className="text-right">Amount</Th>
                </tr>
              </THead>
              <TBody>
                {earnings.entries.map((e) => (
                  <Tr key={e.id}>
                    <Td className="whitespace-nowrap text-muted">
                      <Time iso={e.created_at} />
                    </Td>
                    <Td>
                      <Badge>{humanize(e.kind)}</Badge>
                      {e.ref && <div className="font-mono text-[11.5px] text-faint">{e.ref}</div>}
                    </Td>
                    <Td className={`tabular whitespace-nowrap text-right font-medium ${Number(e.amount) < 0 ? "text-danger" : ""}`}>
                      {money(e.amount, e.currency ?? earnings.currency ?? "EUR")}
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
        <PayoutForm complete={me.tax_info_complete} country={me.country ?? ""} />
      </div>
    </>
  );
}
