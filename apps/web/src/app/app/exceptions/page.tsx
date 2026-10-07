import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Badge, type Tone } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { Time } from "@/components/ui/time";
import { humanize } from "@/lib/format";
import { reasonText } from "@/lib/reasons";
import { getMe, withAuth } from "@/lib/server-api";

export const metadata: Metadata = { title: "Exceptions" };

// routes/jobs.py /exceptions kinds
const KIND_TONE: Record<string, Tone> = {
  job_failed: "danger",
  segment_blocked: "danger",
  term_question: "info",
  overdue: "warn",
  client_review: "accent",
};

const KIND_ACTION: Record<string, string> = {
  job_failed: "Open the job",
  segment_blocked: "Fix or approve the segment",
  term_question: "Answer the question",
  overdue: "Open the job",
  client_review: "Review and approve",
};

export default async function ExceptionsPage() {
  const { user } = await getMe();
  if (user.role !== "pm") redirect("/app");
  const { items } = await withAuth((api) => api.exceptions({ limit: 200 }), "/app/exceptions");
  return (
    <>
      <PageHeader
        title="Exceptions"
        description="Only what needs a human: failed jobs, blocked segments, waiting for a reviewer, open questions. Everything else is running on its own."
      />
      <Card>
        {items.length === 0 ? (
          <EmptyState title="Nothing needs you" description="When a job needs a decision it shows up here." />
        ) : (
          <ul className="divide-y divide-border">
            {items.map((x, i) => (
              <li key={`${x.job_id}-${x.segment_id ?? ""}-${i}`} className="flex flex-col gap-1.5 px-4 py-3 sm:flex-row sm:items-start sm:gap-4">
                <div className="w-40 shrink-0">
                  <Badge tone={KIND_TONE[x.kind] ?? "neutral"}>{humanize(x.kind)}</Badge>
                </div>
                <div className="min-w-0 flex-1 text-[13.5px]">
                  <p>{reasonText(x.reason)}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[12.5px]">
                    <Link
                      href={x.kind === "term_question" ? "/app/term-questions" : `/app/jobs/${x.job_id}${x.kind === "segment_blocked" ? "?decision=blocked" : ""}`}
                      className="font-medium text-accent hover:underline"
                    >
                      {KIND_ACTION[x.kind] ?? "Open"}
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
