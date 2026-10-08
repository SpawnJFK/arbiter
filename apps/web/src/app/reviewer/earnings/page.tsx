import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { withAuth } from "@/lib/server-api";
import { PayoutForm } from "./payout-form";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.earnings.earningsPayouts") };
}

export default async function EarningsPage() {
  const { f, t } = await getI18n();
  const [earnings, me] = await withAuth((api) => Promise.all([api.earnings(), api.reviewerMe()]), "/reviewer/earnings");
  return (
    <>
      <PageHeader title={t("reviewer.earnings.earningsPayouts")} description={t("reviewer.earnings.everyDecisionYouSubmitIs")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat tone="ok" label={t("reviewer.earnings.available")} value={f.money(earnings.balance)} hint={t("reviewer.earnings.paidOutFrom", { payout_threshold: f.money(me.payout_threshold) })} />
        <Stat tone="warn" label={t("reviewer.earnings.inPayout")} value={f.money(earnings.pending)} hint={t("reviewer.earnings.accruedOrSentNotYet")} />
        <Stat label={t("reviewer.earnings.paidToDate")} value={f.money(earnings.paid)} />
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader title={t("reviewer.earnings.ledger")} />
          {earnings.entries.length === 0 ? (
            <EmptyState title={t("reviewer.earnings.noEntriesYet")} description={t("reviewer.earnings.acceptEditOrEscalateA")} />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>{t("reviewer.earnings.date")}</Th>
                  <Th>{t("reviewer.earnings.entry")}</Th>
                  <Th className="text-right">{t("reviewer.earnings.amount")}</Th>
                </tr>
              </THead>
              <TBody>
                {earnings.entries.map((e) => (
                  <Tr key={e.id}>
                    <Td className="whitespace-nowrap text-muted">
                      <Time iso={e.created_at} />
                    </Td>
                    <Td>
                      <Badge>{t.enumLabel(e.kind)}</Badge>
                      {e.ref && <div className="font-mono text-[11.5px] text-faint">{e.ref}</div>}
                    </Td>
                    <Td className={`tabular whitespace-nowrap text-right font-medium ${Number(e.amount) < 0 ? "text-danger" : ""}`}>
                      {f.money(e.amount, e.currency ?? earnings.currency ?? "EUR")}
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
