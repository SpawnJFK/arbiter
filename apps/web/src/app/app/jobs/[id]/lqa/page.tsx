import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { Icons } from "@/components/icons";
import { AnchorButton } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { LqaView } from "./lqa-view";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.jobs.lqa.title") };
}

export default async function LqaPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const next = `/app/jobs/${id}/lqa`;
  const [{ user }, job, lqa, settings] = await Promise.all([
    getMe(),
    withAuth((api) => api.job(id), next),
    withAuth((api) => api.jobLqa(id), next),
    withAuth((api) => api.lqaSettings(), next),
  ]);
  const dl = (kind: string) => `/api/proxy/jobs/${encodeURIComponent(job.id)}/lqa.${kind}`;
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href={`/app/jobs/${job.id}`} className="hover:text-fg">
            {t("app.jobs.editor.backToJob")}
          </Link>
        }
        title={t("app.jobs.lqa.heading", { file: job.filename ?? job.id, lang: job.target_lang })}
        description={t("app.jobs.lqa.description")}
        actions={
          <>
            <AnchorButton href={dl("pdf")} download>
              <Icons.download className="size-4" /> {t("app.jobs.lqa.exportPdf")}
            </AnchorButton>
            <AnchorButton href={dl("xlsx")} download>
              <Icons.download className="size-4" /> {t("app.jobs.lqa.exportXlsx")}
            </AnchorButton>
          </>
        }
      />
      <LqaView lqa={lqa} settings={settings} canEdit={user.role === "pm"} />
    </>
  );
}
