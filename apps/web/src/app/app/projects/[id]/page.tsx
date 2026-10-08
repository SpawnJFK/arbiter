import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { Badge, JobStateBadge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, PageHeader, Progress } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { OUTPUT_STATES, TERMINAL_JOB_STATES } from "@/lib/types";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.projects.detail.project") };
}


export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { f, t } = await getI18n();
  const { id } = await params;
  const project = await withAuth((api) => api.project(id), `/app/projects/${id}`);
  const jobs = project.jobs ?? [];
  const running = jobs.some((j) => !TERMINAL_JOB_STATES.includes(j.state));

  return (
    <>
      <AutoRefresh active={running} intervalMs={5_000} />
      <PageHeader
        eyebrow={
          <Link href="/app/projects" className="hover:text-fg">
            {t("app.projects.detail.projects")}
          </Link>
        }
        title={project.name}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {f.langName(project.source_lang)} → {project.target_langs.map((l) => f.langName(l)).join(", ")}
            </span>
            <Badge tone={project.tier === "hybrid" || project.tier === "full" ? "violet" : "accent"}>{t(`tier.${project.tier}.label`)}</Badge>
            <span>{contentTypeLabel(t, project.content_type)}</span>
            {project.due_at && (
              <span>
                {t("app.projects.detail.due")} <Time iso={project.due_at} />
              </span>
            )}
          </span>
        }
      />
      <Card>
        <CardHeader title={t("app.projects.detail.jobs")} description={t("app.projects.detail.oneJobPerTargetLanguage")} />
        {jobs.length === 0 ? (
          <EmptyState title={t("app.projects.detail.noJobs")} description={t("app.projects.detail.jobsAppearHereAsSoon")} />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>{t("app.projects.detail.target")}</Th>
                <Th>{t("app.projects.detail.state")}</Th>
                <Th className="w-48">{t("app.projects.detail.progress")}</Th>
                <Th className="hidden text-right md:table-cell">{t("app.projects.detail.segments")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("app.projects.detail.auto")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("app.projects.detail.aiReviewed")}</Th>
                <Th className="hidden text-right lg:table-cell">{t("app.projects.detail.human")}</Th>
                <Th className="hidden sm:table-cell">{t("app.projects.detail.delivered")}</Th>
              </tr>
            </THead>
            <TBody>
              {jobs.map((j) => (
                <Tr key={j.id}>
                  <Td>
                    <Link href={`/app/jobs/${j.id}`} className="font-medium hover:text-accent hover:underline">
                      {f.langName(j.target_lang)}
                    </Link>
                    <div className="font-mono text-[11.5px] text-faint">{j.id}</div>
                  </Td>
                  <Td>
                    <JobStateBadge state={j.state} />
                    {j.failure_reason && <div className="mt-1 max-w-xs text-[12px] text-danger">{j.failure_reason}</div>}
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Progress value={j.progress} tone={j.state === "failed" ? "danger" : OUTPUT_STATES.includes(j.state) ? "ok" : "accent"} />
                      <span className="tabular w-9 text-right text-[12px] text-muted">{Math.round(j.progress * 100)}%</span>
                    </div>
                  </Td>
                  <Td className="tabular hidden text-right md:table-cell">{f.num(j.segment_count)}</Td>
                  <Td className="tabular hidden text-right text-ok lg:table-cell">{f.num(j.auto_approved_count)}</Td>
                  <Td className="tabular hidden text-right lg:table-cell">{f.num(j.ai_reviewed_count)}</Td>
                  <Td className="tabular hidden text-right lg:table-cell">{f.num(j.review_count)}</Td>
                  <Td className="hidden text-muted sm:table-cell">
                    <Time iso={j.delivered_at} mode="relative" />
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
