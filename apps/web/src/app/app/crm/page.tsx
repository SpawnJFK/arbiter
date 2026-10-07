import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { TIER_LABEL } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import { AccountFilters, NewAccountButton } from "./account-form";

export const metadata: Metadata = { title: "Accounts" };

export default async function AccountsPage({ searchParams }: { searchParams: Promise<{ q?: string; kind?: string; status?: string }> }) {
  const sp = await searchParams;
  const kind = sp.kind === "client" || sp.kind === "prospect" ? sp.kind : "";
  const status = sp.status === "archived" ? "archived" : "active";
  const [accounts, workflows, priceLists] = await withAuth(
    (api) => Promise.all([api.accounts({ q: sp.q, kind, status, limit: 200 }), api.workflows({ limit: 200 }), api.priceLists({ limit: 200 })]),
    "/app/crm",
  );
  const wfName = new Map(workflows.items.map((w) => [w.id, w.name]));
  const plName = new Map(priceLists.items.map((p) => [p.id, p.name]));
  return (
    <>
      <PageHeader
        title="Accounts"
        description="Clients and prospects, with the defaults their projects start from: tier, workflow and price list."
        actions={<NewAccountButton workflows={workflows.items} priceLists={priceLists.items} />}
      />
      <AccountFilters q={sp.q ?? ""} kind={kind} status={status} />
      <Card>
        {accounts.items.length === 0 ? (
          <EmptyState
            title={sp.q || kind ? "No accounts match" : "No accounts yet"}
            description={sp.q || kind ? "Try another search." : "Add your first client, or describe your agency to the assistant and let it set up accounts for you."}
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Name</Th>
                <Th>Kind</Th>
                <Th className="hidden md:table-cell">Industry</Th>
                <Th className="hidden lg:table-cell">Default tier</Th>
                <Th className="hidden lg:table-cell">Workflow</Th>
                <Th className="hidden xl:table-cell">Price list</Th>
                <Th className="hidden sm:table-cell">Since</Th>
              </tr>
            </THead>
            <TBody>
              {accounts.items.map((a) => (
                <Tr key={a.id}>
                  <Td>
                    <Link href={`/app/crm/${a.id}`} className="font-medium hover:text-accent hover:underline">
                      {a.name}
                    </Link>
                    {a.country && <span className="ml-2 text-[12px] text-faint">{a.country}</span>}
                  </Td>
                  <Td>
                    <Badge tone={a.kind === "client" ? "ok" : "info"}>{a.kind === "client" ? "Client" : "Prospect"}</Badge>
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{a.industry ?? "–"}</Td>
                  <Td className="hidden lg:table-cell">{a.default_tier ? TIER_LABEL[a.default_tier] : <span className="text-faint">Org default</span>}</Td>
                  <Td className="hidden max-w-56 truncate text-muted lg:table-cell">{a.workflow_template_id ? wfName.get(a.workflow_template_id) ?? "–" : "–"}</Td>
                  <Td className="hidden text-muted xl:table-cell">{a.price_list_id ? plName.get(a.price_list_id) ?? "–" : "–"}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={a.created_at} mode="relative" />
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
