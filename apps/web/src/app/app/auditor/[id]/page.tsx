import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AutoRefresh } from "@/components/auto-refresh";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { AuditStateBadge } from "../audit-list";
import { AuditReport } from "./audit-report";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.auditor.report") };
}

export default async function AuditPage({ params }: { params: Promise<{ id: string }> }) {
  const { t } = await getI18n();
  const { id } = await params;
  const next = `/app/auditor/${id}`;
  const [{ user }, audit] = await Promise.all([getMe(), withAuth((api) => api.audit(id), next)]);
  const first = audit.state === "done" ? await withAuth((api) => api.auditSegments(id, { limit: 100 }), next) : null;
  return (
    <>
      <AutoRefresh active={audit.state === "queued" || audit.state === "running"} intervalMs={2_000} />
      <PageHeader
        eyebrow={
          <Link href="/app/auditor" className="hover:text-fg">
            {t("app.auditor.title")}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-2">
            {audit.name}
            <span className="font-normal text-muted">
              {audit.source_lang} → {audit.target_lang}
            </span>
            <AuditStateBadge audit={audit} />
          </span>
        }
        description={t("app.auditor.reportDescription", { file: audit.filename, format: audit.input_format.toUpperCase() })}
      />
      <AuditReport audit={audit} first={first} canRetry={user.role === "pm"} />
    </>
  );
}
