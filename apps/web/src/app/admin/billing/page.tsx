import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { OrgOverride } from "./org-override";
import { PlansEditor } from "./plans-editor";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("admin.billing.title") };
}

export default async function AdminBillingPage({ searchParams }: { searchParams: Promise<{ org?: string }> }) {
  const { org } = await searchParams;
  const { t } = await getI18n();
  const [plans, orgs, overview] = await withAuth(
    (api) => Promise.all([api.adminPlans(), api.adminOrgs({ limit: 200 }), org ? api.adminOrgBilling(org) : Promise.resolve(null)]),
    "/admin/billing",
  );
  return (
    <>
      <PageHeader title={t("admin.billing.title")} description={t("admin.billing.description")} />
      <div className="space-y-6">
        <OrgOverride orgs={orgs.items} plans={plans.items} overview={overview} orgId={org ?? null} />
        <PlansEditor plans={plans.items} providers={plans.providers} />
      </div>
    </>
  );
}
