import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import Link from "next/link";
import { AddonList } from "@/components/addon-list";
import { ModuleList } from "@/components/module-list";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("platform.adminOrg.metaTitle") };
}

export default async function AdminOrgPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { t } = await getI18n();
  const org = await withAuth((api) => api.adminOrg(id), `/admin/orgs/${id}`);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/admin/orgs" className="hover:text-fg">
            {t("admin.orgs.organisations")}
          </Link>
        }
        title={org.name}
        description={t("platform.adminOrg.description", { slug: org.slug, plan: t.enumLabel(org.plan) })}
      />
      <Card>
        <CardHeader title={t("platform.modules.title")} description={t("platform.modules.adminDescription")} />
        <ModuleList catalog={org.catalog} orgId={org.id} />
      </Card>
      {org.addons && org.addons.length > 0 && (
        <Card className="mt-6">
          <CardHeader title={t("platform.addons.title")} description={t("platform.addons.adminDescription")} />
          <AddonList addons={org.addons} />
        </Card>
      )}
    </>
  );
}
