import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { withAuth } from "@/lib/server-api";
import { RunPayoutsButton } from "./run-button";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.payouts.payouts") };
}

export default async function PayoutsPage() {
  const { f, t } = await getI18n();
  const { items } = await withAuth((api) => api.adminPayouts({ limit: 200 }), "/admin/payouts");
  return (
    <>
      <PageHeader
        title={t("admin.payouts.payouts")}
        description={t("admin.payouts.aRunPaysEveryReviewer")}
        actions={<RunPayoutsButton />}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t("admin.payouts.noPayoutsYet")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("admin.payouts.payout")}</Th>
                <Th>{t("admin.payouts.reviewer")}</Th>
                <Th className="text-right">{t("admin.payouts.amount")}</Th>
                <Th>{t("admin.payouts.state")}</Th>
                <Th className="hidden sm:table-cell">{t("admin.payouts.created")}</Th>
              </tr>
            </THead>
            <TBody>
              {items.map((p) => (
                <Tr key={p.id}>
                  <Td className="font-mono text-[12.5px]">{p.id}</Td>
                  <Td className="font-mono text-[12.5px] text-muted">{p.reviewer_id}</Td>
                  <Td className="tabular text-right font-medium">{f.money(p.amount)}</Td>
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
