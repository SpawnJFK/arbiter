import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { WorkflowEditor } from "./editor";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.workflows.detail.workflow") };
}

export default async function WorkflowPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ from?: string }> }) {
  const { t } = await getI18n();
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
            {t("app.workflows.detail.workflows")}
          </Link>
        }
        title={isNew ? (wf ? t("app.workflows.detail.newWorkflowFrom", { name: wf.name }) : t("app.workflows.detail.newWorkflow")) : wf!.name}
      />
      <WorkflowEditor workflow={isNew ? null : wf} template={isNew ? wf : null} regulated={org?.regulated ?? false} />
    </>
  );
}
