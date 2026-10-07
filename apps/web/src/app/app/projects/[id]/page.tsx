import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { Badge, JobStateBadge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, PageHeader, Progress } from "@/components/ui/misc";
import { TBody, THead, Table, Td, Th, Tr } from "@/components/ui/table";
import { Time } from "@/components/ui/time";
import { langName, num, TIER_LABEL } from "@/lib/format";
import { contentTypeLabel } from "@/lib/langs";
import { withAuth } from "@/lib/server-api";
import { OUTPUT_STATES, TERMINAL_JOB_STATES } from "@/lib/types";

export const metadata: Metadata = { title: "Project" };


export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
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
            Projects
          </Link>
        }
        title={project.name}
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {langName(project.source_lang)} → {project.target_langs.map(langName).join(", ")}
            </span>
            <Badge tone={project.tier === "hybrid" || project.tier === "full" ? "violet" : "accent"}>{TIER_LABEL[project.tier]}</Badge>
            <span>{contentTypeLabel(project.content_type)}</span>
            {project.due_at && (
              <span>
                Due <Time iso={project.due_at} />
              </span>
            )}
          </span>
        }
      />
      <Card>
        <CardHeader title="Jobs" description="One job per target language. Open a job to see every segment and the evidence behind it." />
        {jobs.length === 0 ? (
          <EmptyState title="No jobs" description="Jobs appear here as soon as the project is created." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Target</Th>
                <Th>State</Th>
                <Th className="w-48">Progress</Th>
                <Th className="hidden text-right md:table-cell">Segments</Th>
                <Th className="hidden text-right lg:table-cell">Auto</Th>
                <Th className="hidden text-right lg:table-cell">AI reviewed</Th>
                <Th className="hidden text-right lg:table-cell">Human</Th>
                <Th className="hidden sm:table-cell">Delivered</Th>
              </tr>
            </THead>
            <TBody>
              {jobs.map((j) => (
                <Tr key={j.id}>
                  <Td>
                    <Link href={`/app/jobs/${j.id}`} className="font-medium hover:text-accent hover:underline">
                      {langName(j.target_lang)}
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
                  <Td className="tabular hidden text-right md:table-cell">{num(j.segment_count)}</Td>
                  <Td className="tabular hidden text-right text-ok lg:table-cell">{num(j.auto_approved_count)}</Td>
                  <Td className="tabular hidden text-right lg:table-cell">{num(j.ai_reviewed_count)}</Td>
                  <Td className="tabular hidden text-right lg:table-cell">{num(j.review_count)}</Td>
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
