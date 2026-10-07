import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { humanize, num, TIER_LABEL } from "@/lib/format";
import { withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Organisations" };

export default async function OrgsPage() {
  const { items } = await withAuth((api) => api.adminOrgs({ limit: 200 }), "/admin/orgs");
  return (
    <>
      <PageHeader title="Organisations" description="Customer organisations, their policies, and words and jobs this calendar month." />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="No organisations" />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Organisation</Th>
                <Th>Plan</Th>
                <Th className="hidden md:table-cell">Default tier</Th>
                <Th className="hidden lg:table-cell">No-reviewer policy</Th>
                <Th className="hidden lg:table-cell">Flags</Th>
                <Th className="text-right">Words</Th>
                <Th className="text-right">Jobs</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((o) => (
                <Tr key={o.id}>
                  <Td>
                    <div className="font-medium">{o.name}</div>
                    <div className="font-mono text-[11.5px] text-faint">{o.slug}</div>
                  </Td>
                  <Td>{humanize(o.plan)}</Td>
                  <Td className="hidden md:table-cell">{TIER_LABEL[o.default_tier] ?? o.default_tier}</Td>
                  <Td className="hidden lg:table-cell">{humanize(o.no_reviewer_policy)}</Td>
                  <Td className="hidden lg:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {o.regulated && <Badge tone="warn">Regulated{o.vertical ? `: ${o.vertical.replace(/_/g, " ")}` : ""}</Badge>}
                      {o.ai_subprocessors_opt_in && <Badge tone="info">AI subprocessors</Badge>}
                      <Badge>{o.data_retention_days} d retention</Badge>
                    </div>
                  </Td>
                  <Td className="tabular text-right">{num(o.usage?.words ?? null)}</Td>
                  <Td className="tabular text-right font-medium">{num(o.usage?.jobs ?? null)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
