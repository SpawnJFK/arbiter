import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { money, num, TIER_LABEL } from "@/lib/format";
import { withAuth } from "@/lib/server-api";
import { AccountTabs } from "./account-tabs";

export const metadata: Metadata = { title: "Account" };

export default async function AccountPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string }> }) {
  const { id } = await params;
  const { tab } = await searchParams;
  const [account, workflows, priceLists, projects] = await withAuth(
    (api) => Promise.all([api.account(id), api.workflows({ limit: 200 }), api.priceLists({ limit: 200 }), api.projects({ limit: 200 })]),
    `/app/crm/${id}`,
  );
  const wf = workflows.items.find((w) => w.id === account.workflow_template_id);
  const pl = priceLists.items.find((p) => p.id === account.price_list_id);
  const st = account.stats;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/crm" className="hover:text-fg">
            Accounts
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {account.name}
            <Badge tone={account.kind === "client" ? "ok" : "info"}>{account.kind === "client" ? "Client" : "Prospect"}</Badge>
            {account.status === "archived" && <Badge tone="neutral">Archived</Badge>}
          </span>
        }
        description={
          <span className="flex flex-wrap gap-x-3 gap-y-1">
            {account.industry && <span>{account.industry}</span>}
            {account.country && <span>{account.country}</span>}
            <span>Workflow: {wf ? wf.name : "org default"}</span>
            <span>Tier: {wf ? TIER_LABEL[wf.tier] : account.default_tier ? TIER_LABEL[account.default_tier] : "org default"}</span>
            <span>Prices: {pl ? pl.name : "org default"}</span>
          </span>
        }
        actions={
          <Link
            href={`/app/projects/new?account=${account.id}`}
            className="inline-flex h-8.5 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-accent-fg shadow-card hover:bg-accent-hover"
          >
            New project
          </Link>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Projects" value={num(st.projects)} />
        <Stat label="Active jobs" value={num(st.jobs_active)} tone={st.jobs_active ? "accent" : undefined} />
        <Stat label="Revenue (all time)" value={money(st.revenue_total, account.currency ?? "EUR")} />
        <Stat label="Revenue 90 days" value={money(st.revenue_90d, account.currency ?? "EUR")} />
        <Stat label="Margin 90 days" value={money(st.margin_90d, account.currency ?? "EUR")} tone="ok" />
      </div>
      <AccountTabs
        account={account}
        workflows={workflows.items}
        priceLists={priceLists.items}
        projects={projects.items.filter((p) => p.account_id === account.id)}
        initialTab={tab}
      />
    </>
  );
}
