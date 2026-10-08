import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { AccountTabs } from "./account-tabs";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.crm.detail.account") };
}

export default async function AccountPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string }> }) {
  const { f, t } = await getI18n();
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
            {t("app.crm.detail.accounts")}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {account.name}
            <Badge tone={account.kind === "client" ? "ok" : "info"}>{account.kind === "client" ? t("app.crm.detail.client") : t("app.crm.detail.prospect")}</Badge>
            {account.status === "archived" && <Badge tone="neutral">{t("app.crm.detail.archived")}</Badge>}
          </span>
        }
        description={
          <span className="flex flex-wrap gap-x-3 gap-y-1">
            {account.industry && <span>{account.industry}</span>}
            {account.country && <span>{account.country}</span>}
            <span>{t("app.crm.detail.workflow")} {wf ? wf.name : t("app.crm.detail.orgDefault")}</span>
            <span>{t("app.crm.detail.tier")} {wf ? t(`tier.${wf.tier}.label`) : account.default_tier ? t(`tier.${account.default_tier}.label`) : t("app.crm.detail.orgDefault")}</span>
            <span>{t("app.crm.detail.prices")} {pl ? pl.name : t("app.crm.detail.orgDefault")}</span>
          </span>
        }
        actions={
          <Link
            href={`/app/projects/new?account=${account.id}`}
            className="inline-flex h-8.5 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-accent-fg shadow-card hover:bg-accent-hover"
          >
            {t("app.crm.detail.newProject")}
          </Link>
        }
      />
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label={t("app.crm.detail.projects")} value={f.num(st.projects)} />
        <Stat label={t("app.crm.detail.activeJobs")} value={f.num(st.jobs_active)} tone={st.jobs_active ? "accent" : undefined} />
        <Stat label={t("app.crm.detail.revenueAllTime")} value={f.money(st.revenue_total, account.currency ?? "EUR")} />
        <Stat label={t("app.crm.detail.revenue90Days")} value={f.money(st.revenue_90d, account.currency ?? "EUR")} />
        <Stat label={t("app.crm.detail.margin90Days")} value={f.money(st.margin_90d, account.currency ?? "EUR")} tone="ok" />
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
