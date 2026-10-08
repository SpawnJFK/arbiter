import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { withAuth } from "@/lib/server-api";
import { AccountFilters, NewAccountButton } from "./account-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.crm.accounts") };
}

export default async function AccountsPage({ searchParams }: { searchParams: Promise<{ q?: string; kind?: string; status?: string }> }) {
  const { t } = await getI18n();
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
        title={t("app.crm.accounts")}
        description={t("app.crm.clientsAndProspectsWithThe")}
        actions={<NewAccountButton workflows={workflows.items} priceLists={priceLists.items} />}
      />
      <AccountFilters q={sp.q ?? ""} kind={kind} status={status} />
      <Card>
        {accounts.items.length === 0 ? (
          <EmptyState
            title={sp.q || kind ? t("app.crm.noAccountsMatch") : t("app.crm.noAccountsYet")}
            description={sp.q || kind ? t("app.crm.tryAnotherSearch") : t("app.crm.addYourFirstClientOr")}
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.crm.name")}</Th>
                <Th>{t("app.crm.kind")}</Th>
                <Th className="hidden md:table-cell">{t("app.crm.industry")}</Th>
                <Th className="hidden lg:table-cell">{t("app.crm.defaultTier")}</Th>
                <Th className="hidden lg:table-cell">{t("app.crm.workflow")}</Th>
                <Th className="hidden xl:table-cell">{t("app.crm.priceList")}</Th>
                <Th className="hidden sm:table-cell">{t("app.crm.since")}</Th>
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
                    <Badge tone={a.kind === "client" ? "ok" : "info"}>{a.kind === "client" ? t("app.crm.client") : t("app.crm.prospect")}</Badge>
                  </Td>
                  <Td className="hidden text-muted md:table-cell">{a.industry ?? "–"}</Td>
                  <Td className="hidden lg:table-cell">{a.default_tier ? t(`tier.${a.default_tier}.label`) : <span className="text-faint">{t("app.crm.orgDefault")}</span>}</Td>
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
