import { k } from "@/lib/i18n/core";
import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Badge, type Tone } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { reasonText } from "@/lib/reasons";
import { getMe, withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.exceptions.exceptions") };
}

// routes/jobs.py /exceptions kinds
const KIND_TONE: Record<string, Tone> = {
  job_failed: "danger",
  segment_blocked: "danger",
  term_question: "info",
  overdue: "warn",
  client_review: "accent",
};

const KIND_ACTION: Record<string, string> = {
  job_failed: k("app.exceptions.action.job_failed"),
  segment_blocked: k("app.exceptions.action.segment_blocked"),
  term_question: k("app.exceptions.action.term_question"),
  overdue: k("app.exceptions.action.overdue"),
  client_review: k("app.exceptions.action.client_review"),
};

export default async function ExceptionsPage() {
  const { t } = await getI18n();
  const { user } = await getMe();
  if (user.role !== "pm") redirect("/app");
  const { items } = await withAuth((api) => api.exceptions({ limit: 200 }), "/app/exceptions");
  return (
    <>
      <PageHeader
        title={t("app.exceptions.exceptions")}
        description={t("app.exceptions.onlyWhatNeedsAHuman")}
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title={t("app.exceptions.nothingNeedsYou")} description={t("app.exceptions.whenAJobNeedsA")} />
        ) : (
          <ul className="divide-y divide-border">
            {items.map((x, i) => (
              <li key={`${x.job_id}-${x.segment_id ?? ""}-${i}`} className="flex flex-col gap-1.5 px-4 py-3 sm:flex-row sm:items-start sm:gap-4">
                <div className="w-40 shrink-0">
                  <Badge tone={KIND_TONE[x.kind] ?? "neutral"}>{t.enumLabel(x.kind)}</Badge>
                </div>
                <div className="min-w-0 flex-1 text-[13.5px]">
                  <p>{reasonText(t, x.reason)}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12.5px]">
                    <Link
                      href={x.kind === "term_question" ? "/app/term-questions" : `/app/jobs/${x.job_id}${x.kind === "segment_blocked" ? "?decision=blocked" : ""}`}
                      className="font-medium text-accent hover:underline"
                    >
                      {KIND_ACTION[x.kind] ? t(KIND_ACTION[x.kind]) : t("app.exceptions.open")}
                    </Link>
                    <span className="font-mono text-[12px] text-faint">
                      {x.job_id}
                      {x.segment_id && <> · {x.segment_id}</>}
                    </span>
                  </p>
                </div>
                <div className="shrink-0 text-[12.5px] text-muted">
                  <Time iso={x.created_at} mode="relative" />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
