import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import { AuditList } from "./audit-list";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.auditor.title") };
}

export default async function AuditorPage() {
  const { t } = await getI18n();
  const [{ user }, audits, glossaries] = await Promise.all([
    getMe(),
    withAuth((api) => api.audits({ limit: 50 }), "/app/auditor"),
    withAuth((api) => api.glossaries({ limit: 200 }), "/app/auditor"),
  ]);
  return (
    <>
      <PageHeader title={t("app.auditor.title")} description={t("app.auditor.description")} />
      <AuditList initial={audits.items} glossaries={glossaries.items} canCreate={user.role === "pm"} />
    </>
  );
}
