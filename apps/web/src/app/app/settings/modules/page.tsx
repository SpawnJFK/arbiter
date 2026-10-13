import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { ModuleList } from "@/components/module-list";
import { Card, CardHeader } from "@/components/ui/card";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.modules.metaTitle") };
}

/** Read-only for customers: the platform admin (or a plan purchase) changes entitlements. */
export default async function ModulesPage() {
  const { t } = await getI18n();
  const { catalog } = await withAuth((api) => api.orgModules(), "/app/settings/modules");
  return (
    <Card>
      <CardHeader title={t("platform.modules.title")} description={t("platform.modules.customerDescription")} />
      <ModuleList catalog={catalog} />
    </Card>
  );
}
