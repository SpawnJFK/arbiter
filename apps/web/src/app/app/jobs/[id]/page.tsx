import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { Icons } from "@/components/icons";
import { Badge, JobStateBadge } from "@/components/ui/badge";
import { AnchorButton, Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Callout, PageHeader, Progress } from "@/components/ui/misc";
import { Stat } from "@/components/ui/card";
import { Time } from "@/components/ui/time";
import { langName, money, num, pct, score, TIER_LABEL } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { getMe, withAuth } from "@/lib/server-api";
import type { JobState } from "@/lib/types";
import { CancelJobButton } from "./cancel-button";
import { SegmentTable } from "./segment-table";

export const metadata: Metadata = { title: "Job" };

const TERMINAL: JobState[] = ["delivered", "failed", "cancelled"];

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const next = `/app/jobs/${id}`;
  const [{ user }, job, firstPage, senate] = await Promise.all([
    getMe(),
    withAuth((api) => api.job(id), next),
    withAuth((api) => api.segments(id, { limit: 50 }), next),
    // The Job object has no senate counter; count segments whose decision was the senate.
    withAuth((api) => api.segments(id, { decision: "senate", limit: 200 }), next),
  ]);
  const senateCount = senate.next_offset === null ? num(senate.items.length) : `${num(senate.items.length)}+`;
  const showMoney = user.role === "pm" || user.role === "admin";
  const delivered = job.state === "delivered";
  const dl = (path: string) => `/api/proxy/jobs/${encodeURIComponent(job.id)}${path}`;

  return (
    <>
      <AutoRefresh active={!TERMINAL.includes(job.state)} intervalMs={15_000} />
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-1.5">
            <Link href="/app" className="hover:text-fg">
              Projects
            </Link>
            <span aria-hidden="true">/</span>
            <Link href={`/app/projects/${job.project_id}`} className="hover:text-fg">
              Project
            </Link>
          </span>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {job.filename}
            <span className="font-normal text-muted">
              {job.source_lang} → {job.target_lang}
            </span>
            <JobStateBadge state={job.state} />
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{langName(job.target_lang)}</span>
            <Badge tone={job.tier === "hybrid" || job.tier === "full" ? "violet" : "accent"}>{TIER_LABEL[job.tier]}</Badge>
            <span>{contentTypeLabel(job.content_type)}</span>
            <span className="tabular">
              {num(job.segment_count)} segments · {num(job.word_count)} words
            </span>
            {job.threshold !== null && <span className="tabular">QE threshold {score(job.threshold)}</span>}
          </span>
        }
        actions={
          <>
            {delivered ? (
              <AnchorButton href={dl("/download")} variant="primary" download>
                <Icons.download className="size-4" /> Download
              </AnchorButton>
            ) : (
              <Button variant="primary" disabled title="Available once the job is delivered">
                <Icons.download className="size-4" /> Download
              </Button>
            )}
            <AnchorButton href={dl("/xliff")} download>
              XLIFF
            </AnchorButton>
            <AnchorButton href={dl("/evidence?format=json")} download>
              Evidence JSON
            </AnchorButton>
            <AnchorButton href={dl("/evidence?format=pdf")} download>
              Evidence PDF
            </AnchorButton>
            {!TERMINAL.includes(job.state) && <CancelJobButton jobId={job.id} />}
          </>
        }
      />

      {job.failure_reason && (
        <Callout tone="danger" title="Job failed" className="mb-4">
          {job.failure_reason}
        </Callout>
      )}

      <Card className="mb-4 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]">
          <div className="flex min-w-60 flex-1 items-center gap-3">
            <Progress value={job.progress} tone={job.state === "failed" ? "danger" : delivered ? "ok" : "accent"} />
            <span className="tabular font-medium">{pct(job.progress)}</span>
          </div>
          <span className="text-muted">
            Created <Time iso={job.created_at} />
          </span>
          {job.due_at && (
            <span className="text-muted">
              Due <Time iso={job.due_at} />
            </span>
          )}
          {job.delivered_at && (
            <span className="text-muted">
              Delivered <Time iso={job.delivered_at} />
            </span>
          )}
        </div>
      </Card>

      <div className={`mb-4 grid grid-cols-2 gap-3 ${showMoney ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
        <Stat tone="ok" label="Auto-approved" value={num(job.auto_approved_count)} hint="Cleared threshold + band" />
        <Stat tone="accent" label="Senate" value={senateCount} hint="Decided by the AI senate" />
        <Stat tone="violet" label="Human reviewed" value={num(job.review_count)} hint="Reviewer or your team" />
        <Stat label="AI reviewed" value={num(job.ai_reviewed_count)} hint="Revised by the AI editor" />
        {showMoney && (
          <Stat
            label="Margin"
            value={money(job.margin)}
            hint={`Revenue ${money(job.revenue)} · cost ${money(job.cost)}`}
          />
        )}
      </div>

      <SegmentTable job={job} initial={firstPage} />
    </>
  );
}
