"use client";

import { useRouter } from "next/navigation";
import { StatusBadge } from "@/components/ui/badge";
import { AnchorButton } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { money, num } from "@/lib/format";
import type { Invoice, Usage } from "@/lib/types";

export function Billing({ usage, invoices, period }: { usage: Usage; invoices: Invoice[]; period: string }) {
  const router = useRouter();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="period" className="text-[13px] font-medium">
          Period
        </label>
        <Input
          id="period"
          type="month"
          className="w-44"
          value={period}
          onChange={(e) => e.target.value && router.push(`/app/settings/billing?period=${e.target.value}`)}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Words" value={num(usage.words)} />
        <Stat label="AI units" value={num(usage.ai_units)} hint="Engine, QE and senate calls" />
        <Stat label="Review decisions" value={num(usage.review_decisions)} hint="Human decisions billed" />
        <Stat tone="accent" label="Amount" value={money(usage.amount)} hint={`Period ${usage.period}`} />
      </div>
      <Card>
        <CardHeader title="Invoices" />
        {invoices.length === 0 ? (
          <EmptyState title="No invoices yet" description="Invoices appear here once they are issued." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Invoice</Th>
                <Th>Period</Th>
                <Th className="hidden sm:table-cell">Issued</Th>
                <Th className="text-right">Amount</Th>
                <Th>Status</Th>
                <Th className="text-right">
                  <span className="sr-only">Download</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {invoices.map((i) => (
                <Tr key={i.id}>
                  <Td className="font-mono text-[12.5px]">{i.number ?? i.id}</Td>
                  <Td>{i.period ?? "–"}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={i.issued_at} />
                  </Td>
                  <Td className="tabular text-right font-medium">{money(i.amount, i.currency ?? "EUR")}</Td>
                  <Td>
                    <StatusBadge status={i.status} />
                  </Td>
                  <Td className="text-right">
                    {i.pdf_url && (
                      <AnchorButton size="sm" variant="ghost" href={i.pdf_url}>
                        PDF
                      </AnchorButton>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
