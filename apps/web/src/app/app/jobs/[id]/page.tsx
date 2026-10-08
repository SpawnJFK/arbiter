import { getI18n } from "@/lib/i18n/server";
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
import { contentTypeLabel } from "@/lib/langs";
import { getMe, withAuth } from "@/lib/server-api";
import { DECISIONS, OUTPUT_STATES, SEGMENT_STATES, TERMINAL_JOB_STATES } from "@/lib/types";
import { CancelJobButton } from "./cancel-button";
import { ClientApproval } from "./client-approval";
import { WorkflowPipeline } from "@/components/workflow-pipeline";
import { stepStatuses } from "@/lib/workflow";
import { SegmentTable } from "./segment-table";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.jobs.detail.job") };
}


export default async function JobPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ decision?: string; state?: string }>;
}) {
  const { f, t } = await getI18n();
  const { id } = await params;
  const sp = await searchParams;
  const decision = DECISIONS.find((d) => d === sp.decision) ?? "";
  const segState = SEGMENT_STATES.find((x) => x === sp.state) ?? "";
  const next = `/app/jobs/${id}`;
  const [{ user }, job, firstPage, senate] = await Promise.all([
    getMe(),
    withAuth((api) => api.job(id), next),
    withAuth((api) => api.segments(id, { limit: 50, decision, state: segState }), next),
    // The Job object has no senate counter; count segments whose decision was the senate.
    withAuth((api) => api.segments(id, { decision: "senate", limit: 200 }), next),
  ]);
  // job.senate_count (Agency OS) is authoritative; older backends only allow counting segments.
  const senateCount =
    typeof job.senate_count === "number" ? f.num(job.senate_count) : senate.next_offset === null ? f.num(senate.items.length) : `${f.num(senate.items.length)}+`;
  const wfSteps = job.workflow?.steps ?? [];
  const showMoney = user.role === "pm" || user.role === "admin";
  const delivered = OUTPUT_STATES.includes(job.state);
  const dl = (path: string) => `/api/proxy/jobs/${encodeURIComponent(job.id)}${path}`;

  return (
    <>
      <AutoRefresh active={!TERMINAL_JOB_STATES.includes(job.state)} intervalMs={5_000} />
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-1.5">
            <Link href="/app/projects" className="hover:text-fg">
              {t("app.jobs.detail.projects")}
            </Link>
            <span aria-hidden="true">/</span>
            <Link href={`/app/projects/${job.project_id}`} className="hover:text-fg">
              {t("app.jobs.detail.project")}
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
            <span>{f.langName(job.target_lang)}</span>
            <Badge tone={job.tier === "hybrid" || job.tier === "full" ? "violet" : "accent"}>{t(`tier.${job.tier}.label`)}</Badge>
            <span>{contentTypeLabel(t, job.content_type)}</span>
            <span className="tabular">
              {t("app.jobs.detail.segmentsWords", { segment_count: f.num(job.segment_count), word_count: f.num(job.word_count) })}
            </span>
            {job.threshold !== null && <span className="tabular">{t("app.jobs.detail.qeThreshold", { threshold: f.score(job.threshold) })}</span>}
          </span>
        }
        actions={
          <>
            {delivered ? (
              <AnchorButton href={dl("/download")} variant="primary" download>
                <Icons.download className="size-4" /> {t("app.jobs.detail.download")}
              </AnchorButton>
            ) : (
              <Button variant="primary" disabled title={t("app.jobs.detail.availableOnceTheJobIs")}>
                <Icons.download className="size-4" /> {t("app.jobs.detail.download")}
              </Button>
            )}
            <AnchorButton href={dl("/xliff")} download>
              {t("app.jobs.detail.xliff")}
            </AnchorButton>
            <AnchorButton href={dl("/evidence?format=json")} download>
              {t("app.jobs.detail.evidenceJson")}
            </AnchorButton>
            <AnchorButton href={dl("/evidence?format=pdf")} download>
              {t("app.jobs.detail.evidencePdf")}
            </AnchorButton>
            {user.role === "pm" && ["draft", "quoted", "running", "review"].includes(job.state) && <CancelJobButton jobId={job.id} />}
          </>
        }
      />

      {job.awaiting_client_approval && <ClientApproval jobId={job.id} />}
      {wfSteps.length > 0 && (
        <Card className="mb-4 px-4 py-3">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[13px]">
            <span className="font-semibold">{t("app.jobs.detail.workflow")}</span>
            <span className="text-muted">{job.workflow?.name}</span>
            {job.workflow?.source === "tier" && <span className="text-[12px] text-faint">{t("app.jobs.detail.tierDefault")}</span>}
            {job.client_approved_at && (
              <span className="ml-auto text-[12.5px] text-ok">
                {t("app.jobs.detail.clientApproved")} <Time iso={job.client_approved_at} mode="relative" />
              </span>
            )}
          </div>
          <WorkflowPipeline steps={wfSteps} statuses={stepStatuses(job, wfSteps)} />
        </Card>
      )}
      {job.no_reviewer_fallback_used && (
        <Callout tone="warn" title={t("app.jobs.detail.reviewerFallbackUsed")} className="mb-4">
          {t("app.jobs.detail.noQualifiedReviewerWasAvailable")}
        </Callout>
      )}
      {job.failure_reason && (
        <Callout tone="danger" title={t("app.jobs.detail.jobFailed")} className="mb-4">
          {job.failure_reason}
        </Callout>
      )}

      <Card className="mb-4 px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13px]">
          <div className="flex min-w-60 flex-1 items-center gap-3">
            <Progress value={job.progress} tone={job.state === "failed" ? "danger" : delivered ? "ok" : "accent"} />
            <span className="tabular font-medium">{f.pct(job.progress)}</span>
          </div>
          <span className="text-muted">
            {t("app.jobs.detail.created")} <Time iso={job.created_at} />
          </span>
          {job.due_at && (
            <span className="text-muted">
              {t("app.jobs.detail.due")} <Time iso={job.due_at} />
            </span>
          )}
          {job.delivered_at && (
            <span className="text-muted">
              {t("app.jobs.detail.delivered")} <Time iso={job.delivered_at} />
            </span>
          )}
        </div>
      </Card>

      <div className={`mb-4 grid grid-cols-2 gap-3 ${showMoney ? "lg:grid-cols-5" : "lg:grid-cols-4"}`}>
        <Stat tone="ok" label={t("app.jobs.detail.autoApproved")} value={f.num(job.auto_approved_count)} hint={t("app.jobs.detail.clearedThresholdBand")} />
        <Stat tone="accent" label={t("app.jobs.detail.senate")} value={senateCount} hint={t("app.jobs.detail.segmentsTheAiSenateReviewed")} />
        <Stat tone="violet" label={t("app.jobs.detail.routedToHumans")} value={f.num(job.review_count)} hint={t("app.jobs.detail.sentToAReviewerOr")} />
        <Stat label={t("app.jobs.detail.aiReviewed")} value={f.num(job.ai_reviewed_count)} hint={t("app.jobs.detail.revisedByTheAiEditor")} />
        {showMoney && (
          <Stat
            label={t("app.jobs.detail.margin")}
            value={f.money(job.margin)}
            hint={t("app.jobs.detail.revenueCost", { revenue: f.money(job.revenue), cost: f.money(job.cost) })}
          />
        )}
      </div>

      <SegmentTable key={`${job.state}-${decision}-${segState}`} job={job} initial={firstPage} initialDecision={decision} initialState={segState} />
    </>
  );
}
