import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { AddonList } from "@/components/addon-list";
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
  const { catalog, addons } = await withAuth((api) => api.orgModules(), "/app/settings/modules");
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t("platform.modules.title")} description={t("platform.modules.customerDescription")} />
        <ModuleList catalog={catalog} />
      </Card>
      {addons && addons.length > 0 && (
        <Card>
          <CardHeader title={t("platform.addons.title")} description={t("platform.addons.customerDescription")} />
          <AddonList addons={addons} />
        </Card>
      )}
    </div>
  );
}
