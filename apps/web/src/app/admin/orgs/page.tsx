import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.orgs.organisations") };
}

export default async function OrgsPage() {
  const { f, t } = await getI18n();
  const { items } = await withAuth((api) => api.adminOrgs({ limit: 200 }), "/admin/orgs");
  return (
    <>
      <PageHeader title={t("admin.orgs.organisations")} description={t("admin.orgs.customerOrganisationsTheirPoliciesAnd")} />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t("admin.orgs.noOrganisations")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("admin.orgs.organisation")}</Th>
                <Th>{t("admin.orgs.plan")}</Th>
                <Th className="hidden md:table-cell">{t("admin.orgs.defaultTier")}</Th>
                <Th className="hidden lg:table-cell">{t("admin.orgs.noReviewerPolicy")}</Th>
                <Th className="hidden lg:table-cell">{t("admin.orgs.flags")}</Th>
                <Th className="text-right">{t("admin.orgs.words")}</Th>
                <Th className="text-right">{t("admin.orgs.jobs")}</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((o) => (
                <Tr key={o.id}>
                  <Td>
                    <div className="font-medium">{o.name}</div>
                    <div className="font-mono text-[11.5px] text-faint">{o.slug}</div>
                  </Td>
                  <Td>{t.enumLabel(o.plan)}</Td>
                  <Td className="hidden md:table-cell">{t(`tier.${o.default_tier}.label`) ?? o.default_tier}</Td>
                  <Td className="hidden lg:table-cell">{t.enumLabel(o.no_reviewer_policy)}</Td>
                  <Td className="hidden lg:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {o.regulated && <Badge tone="warn">{o.vertical ? t("admin.orgs.regulatedVertical", { vertical: t.enumLabel(o.vertical) }) : t("admin.orgs.regulated")}</Badge>}
                      {o.ai_subprocessors_opt_in && <Badge tone="info">{t("admin.orgs.aiSubprocessors")}</Badge>}
                      <Badge>{t("admin.orgs.dRetention", { data_retention_days: o.data_retention_days })}</Badge>
                    </div>
                  </Td>
                  <Td className="tabular text-right">{f.num(o.usage?.words ?? null)}</Td>
                  <Td className="tabular text-right font-medium">{f.num(o.usage?.jobs ?? null)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </>
  );
}
