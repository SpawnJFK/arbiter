import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { JobStateBadge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { Editor } from "./editor";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.jobs.editor.title") };
}

export default async function EditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const next = `/app/jobs/${id}/editor`;
  const [{ user }, job, first] = await Promise.all([
    getMe(),
    withAuth((api) => api.job(id), next),
    withAuth((api) => api.editorSegments(id, { limit: 200 }), next),
  ]);
  return (
    <>
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-1.5">
            <Link href={`/app/jobs/${job.id}`} className="hover:text-fg">
              {t("app.jobs.editor.backToJob")}
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
        description={t("app.jobs.editor.description")}
      />
      <Editor job={job} role={user.role} initial={first} />
    </>
  );
}
