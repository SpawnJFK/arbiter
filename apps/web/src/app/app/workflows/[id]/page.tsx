import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { WorkflowEditor } from "./editor";

export const metadata: Metadata = { title: "Workflow" };

export default async function WorkflowPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ from?: string }> }) {
  const { id } = await params;
  const { from } = await searchParams;
  const { org } = await getMe();
  const isNew = id === "new";
  const wf = await withAuth((api) => (isNew ? (from ? api.workflow(from) : Promise.resolve(null)) : api.workflow(id)), `/app/workflows/${id}`);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/app/workflows" className="hover:text-fg">
            Workflows
          </Link>
        }
        title={isNew ? (wf ? `New workflow from "${wf.name}"` : "New workflow") : wf!.name}
      />
      <WorkflowEditor workflow={isNew ? null : wf} template={isNew ? wf : null} regulated={org?.regulated ?? false} />
    </>
  );
}
