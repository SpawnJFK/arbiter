import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { StatusBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Callout, EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("reviewer.reviewerDashboard") };
}

export default async function ReviewerDashboard() {
  const { f, t } = await getI18n();
  const [me, tests] = await withAuth((api) => Promise.all([api.reviewerMe(), api.reviewerTests()]), "/reviewer");
  const activePairs = me.pairs.filter((p) => p.status === "active").length;
  const availableTests = tests.items.filter((item) => item.status === "available");
  const belowThreshold = Number(me.balance) < Number(me.payout_threshold);

  return (
    <>
      <PageHeader
        title={t("reviewer.dashboard")}
        description={t("reviewer.statusDomains", { status: t.enumLabel(me.status), domains: me.domains.map((d) => contentTypeLabel(t, d)).join(", ") || t("reviewer.noDomains") })}
        actions={
          <ButtonLink href="/reviewer/cockpit" variant="primary" aria-disabled={activePairs === 0}>
            {t("reviewer.startReviewing")} <Icons.arrowRight className="size-4" />
          </ButtonLink>
        }
      />
      {!me.tax_info_complete && (
        <Callout tone="warn" title={t("reviewer.payoutDetailsMissing")} className="mb-4">
          {t("reviewer.yourEarningsKeepAccruingBut")}{" "}
          <Link href="/reviewer/earnings#payout" className="font-medium underline">
            {t("reviewer.addThemNow")}
          </Link>
          .
        </Callout>
      )}
      {activePairs === 0 && (
        <Callout tone="info" title={t("reviewer.noActivePairsYet")} className="mb-4">
          {t("reviewer.passATestForOne")}
        </Callout>
      )}
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat tone="accent" label={t("reviewer.level")} value={t.enumLabel(String(me.level))} hint={t("reviewer.raisedByThePlatformAs")} />
        <Stat tone="ok" label={t("reviewer.qualityScore")} value={me.score === null ? "–" : `${me.score.toFixed(0)} / 100`} hint={t("reviewer.fromBlindControlSamples")} />
        <Stat label={t("reviewer.activePairs")} value={`${activePairs} of ${me.pairs.length}`} />
        <Stat
          tone={belowThreshold ? undefined : "ok"}
          label={t("reviewer.balance")}
          value={f.money(me.balance)}
          hint={belowThreshold ? t("reviewer.payoutFrom", { payout_threshold: f.money(me.payout_threshold) }) : t("reviewer.eligibleForTheNextPayout")}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title={t("reviewer.languagePairs")} />
          <Table>
            <THead>
              <tr>
                <Th>{t("reviewer.pair")}</Th>
                <Th>{t("reviewer.status")}</Th>
                <Th className="text-right">{t("reviewer.score")}</Th>
              </tr>
            </THead>
            <TBody>
              {me.pairs.map((p) => (
                <Tr key={`${p.source_lang}-${p.target_lang}`}>
                  <Td>
                    {f.langName(p.source_lang)} → {f.langName(p.target_lang)}
                    <span className="ml-2 font-mono text-[12px] text-faint">
                      {p.source_lang}-{p.target_lang}
                    </span>
                  </Td>
                  <Td>
                    <StatusBadge status={p.status} />
                  </Td>
                  <Td className="tabular text-right">{p.score === null || p.status !== "active" ? "–" : p.score.toFixed(0)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        </Card>
        <Card>
          <CardHeader title={t("reviewer.testsYouCanTake")} actions={<ButtonLink href="/reviewer/tests" size="sm" variant="ghost">{t("reviewer.allTests")}</ButtonLink>} />
          {availableTests.length === 0 ? (
            <EmptyState title={t("reviewer.noOpenTests")} description={t("reviewer.newTestsUnlockAsYou")} />
          ) : (
            <ul className="divide-y divide-border">
              {availableTests.map((availableTest) => (
                <li key={availableTest.id} className="flex items-center gap-3 px-4 py-2.5 text-[13.5px]">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {availableTest.source_lang} → {availableTest.target_lang} · {contentTypeLabel(t, availableTest.domain)}
                    </div>
                    <div className="text-[12.5px] text-muted">
                      {t("reviewer.min", { kind: t.enumLabel(availableTest.kind), time_limit_min: availableTest.time_limit_min })}
                    </div>
                  </div>
                  <ButtonLink href={`/reviewer/tests/${availableTest.id}`} size="sm">
                    {t("reviewer.takeTest")}
                  </ButtonLink>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
