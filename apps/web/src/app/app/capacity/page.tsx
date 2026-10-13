import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { withAuth } from "@/lib/server-api";
import { Planner } from "./planner";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.capacity.capacity") };
}

function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export default async function CapacityPage({ searchParams }: { searchParams: Promise<{ start?: string }> }) {
  const { f, t } = await getI18n();
  const sp = await searchParams;
  const start = /^\d{4}-\d{2}-\d{2}$/.test(sp.start ?? "") ? sp.start : undefined;
  const [tl, risk] = await withAuth((api) => Promise.all([api.timeline({ start, days: 14 }), api.deadlineRisk(false)]), "/app/capacity");
  const jobsByDay = new Map<string, typeof tl.jobs>();
  for (const j of tl.jobs) {
    const d = j.due_at.slice(0, 10);
    jobsByDay.set(d, [...(jobsByDay.get(d) ?? []), j]);
  }
  const atRisk = risk.items.filter((r) => r.at_risk);
  return (
    <>
      <PageHeader title={t("app.capacity.capacity")} description={t("app.capacity.description")} />
      <div className="mb-4">
        <Planner />
      </div>

      <Card className="mb-4">
        <CardHeader
          title={t("app.capacity.timeline")}
          description={t("app.capacity.timelineHint")}
          actions={
            <span className="flex gap-2 text-[13px]">
              <Link href={`/app/capacity?start=${addDays(tl.start, -7)}`} className="text-accent hover:underline">
                {t("app.capacity.previousWeek")}
              </Link>
              <Link href={`/app/capacity?start=${addDays(tl.start, 7)}`} className="text-accent hover:underline">
                {t("app.capacity.nextWeek")}
              </Link>
            </span>
          }
        />
        {tl.vendors.length === 0 ? (
          <EmptyState title={t("app.capacity.noVendors")} description={t("app.capacity.noVendorsHint")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th className="sticky left-0 bg-subtle">{t("app.capacity.vendor")}</Th>
                {tl.days.map((d) => (
                  <Th key={d} className="text-center">
                    {f.dateOnly(d).replace(/,? \d{4}$/, "")}
                  </Th>
                ))}
              </tr>
            </THead>
            <TBody>
              <Tr>
                <Td className="sticky left-0 bg-surface text-[12.5px] font-medium text-muted">{t("app.capacity.jobsDue")}</Td>
                {tl.days.map((d) => (
                  <Td key={d} className="text-center">
                    {(jobsByDay.get(d) ?? []).map((j) => (
                      <Link key={j.job_id} href={`/app/jobs/${j.job_id}`} title={`${j.project ?? j.job_id} ${j.source_lang}→${j.target_lang}`}>
                        <Badge tone={j.at_risk ? "danger" : "neutral"} className="mb-0.5">
                          {j.target_lang}
                        </Badge>
                      </Link>
                    ))}
                  </Td>
                ))}
              </Tr>
              {tl.vendors.map((v) => (
                <Tr key={v.vendor_id}>
                  <Td className="sticky left-0 bg-surface">
                    <Link href={`/app/vendors/${v.vendor_id}`} className="font-medium hover:text-accent hover:underline">
                      {v.name}
                    </Link>
                    <div className="tabular text-[11.5px] text-faint">{t("app.capacity.perDay", { words: f.num(v.capacity_words_per_day) })}</div>
                  </Td>
                  {v.days.map((d) => {
                    const share = d.capacity > 0 ? d.load / d.capacity : 0;
                    return (
                      <Td key={d.date} className="px-1 text-center">
                        <div
                          title={t("app.vendors.detail.dayTitle", { date: d.date, load: d.load, capacity: d.capacity })}
                          className={cn(
                            "tabular rounded px-1 py-1 text-[11.5px]",
                            d.absent
                              ? "bg-warn-subtle text-warn"
                              : d.capacity === 0
                                ? "bg-subtle text-faint"
                                : share >= 1
                                  ? "bg-danger-subtle text-danger"
                                  : share > 0
                                    ? "bg-accent-subtle text-accent"
                                    : "text-muted",
                          )}
                        >
                          {d.absent ? t("app.vendors.detail.absent") : d.capacity === 0 ? t("app.vendors.detail.off") : f.num(d.free)}
                        </div>
                      </Td>
                    );
                  })}
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader title={t("app.capacity.deadlineRisk")} description={t("app.capacity.deadlineRiskHint")} />
        {atRisk.length === 0 ? (
          <EmptyState title={t("app.capacity.noRisk")} description={t("app.capacity.noRiskHint", { count: risk.items.length })} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.capacity.job")}</Th>
                <Th>{t("app.capacity.due")}</Th>
                <Th>{t("app.capacity.estimatedFinish")}</Th>
                <Th className="text-right">{t("app.capacity.wordsLeft")}</Th>
                <Th className="hidden md:table-cell">{t("app.capacity.route")}</Th>
              </tr>
            </THead>
            <TBody>
              {atRisk.map((r) => (
                <Tr key={r.job_id}>
                  <Td>
                    <Link href={`/app/jobs/${r.job_id}`} className="font-medium hover:text-accent hover:underline">
                      {r.project ?? r.job_id}
                    </Link>
                    <div className="text-[12px] text-faint">
                      {r.source_lang} → {r.target_lang}
                    </div>
                  </Td>
                  <Td className="text-[13px]">{f.dateTime(r.due_at)}</Td>
                  <Td className="text-[13px] text-danger">{f.dateTime(r.estimated_finish)}</Td>
                  <Td className="tabular text-right">{f.num(r.remaining_words)}</Td>
                  <Td className="hidden text-[13px] text-muted md:table-cell">
                    {Object.entries(r.routes)
                      .map(([step, v]) => `${t.enumLabel(step)}: ${v.vendor_name ?? t.enumLabel(v.route)}`)
                      .join(" · ")}
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
