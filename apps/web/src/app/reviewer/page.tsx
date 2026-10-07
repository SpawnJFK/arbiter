import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { StatusBadge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Callout, EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { humanize, langName, money } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Reviewer dashboard" };

export default async function ReviewerDashboard() {
  const [me, tests] = await withAuth((api) => Promise.all([api.reviewerMe(), api.reviewerTests()]), "/reviewer");
  const activePairs = me.pairs.filter((p) => p.status === "active").length;
  const availableTests = tests.items.filter((t) => t.status === "available");
  const belowThreshold = Number(me.balance) < Number(me.payout_threshold);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={`Status: ${humanize(me.status)} · domains: ${me.domains.map(contentTypeLabel).join(", ") || "none"}`}
        actions={
          <ButtonLink href="/reviewer/cockpit" variant="primary" aria-disabled={activePairs === 0}>
            Start reviewing <Icons.arrowRight className="size-4" />
          </ButtonLink>
        }
      />
      {!me.tax_info_complete && (
        <Callout tone="warn" title="Payout details missing" className="mb-4">
          Your earnings keep accruing, but we cannot pay out until your tax and payout details are on file.{" "}
          <Link href="/reviewer/earnings#payout" className="font-medium underline">
            Add them now
          </Link>
          .
        </Callout>
      )}
      {activePairs === 0 && (
        <Callout tone="info" title="No active pairs yet" className="mb-4">
          Pass a test for one of your language pairs to start receiving tasks.
        </Callout>
      )}
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat tone="accent" label="Level" value={humanize(String(me.level))} hint="Raised by the platform as your record grows" />
        <Stat tone="ok" label="Quality score" value={me.score === null ? "–" : `${me.score.toFixed(0)} / 100`} hint="From blind control samples" />
        <Stat label="Active pairs" value={`${activePairs} of ${me.pairs.length}`} />
        <Stat
          tone={belowThreshold ? undefined : "ok"}
          label="Balance"
          value={money(me.balance)}
          hint={belowThreshold ? `Payout from ${money(me.payout_threshold)}` : "Eligible for the next payout run"}
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title="Language pairs" />
          <Table>
            <THead>
              <tr>
                <Th>Pair</Th>
                <Th>Status</Th>
                <Th className="text-right">Score</Th>
              </tr>
            </THead>
            <TBody>
              {me.pairs.map((p) => (
                <Tr key={`${p.source_lang}-${p.target_lang}`}>
                  <Td>
                    {langName(p.source_lang)} → {langName(p.target_lang)}
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
          <CardHeader title="Tests you can take" actions={<ButtonLink href="/reviewer/tests" size="sm" variant="ghost">All tests</ButtonLink>} />
          {availableTests.length === 0 ? (
            <EmptyState title="No open tests" description="New tests unlock as you level up." />
          ) : (
            <ul className="divide-y divide-border">
              {availableTests.map((t) => (
                <li key={t.id} className="flex items-center gap-3 px-4 py-2.5 text-[13.5px]">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">
                      {t.source_lang} → {t.target_lang} · {contentTypeLabel(t.domain)}
                    </div>
                    <div className="text-[12.5px] text-muted">
                      {humanize(t.kind)} · {t.time_limit_min} min
                    </div>
                  </div>
                  <ButtonLink href={`/reviewer/tests/${t.id}`} size="sm">
                    Take test
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
