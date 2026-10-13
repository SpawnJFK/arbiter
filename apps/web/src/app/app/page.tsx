import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { hasModule } from "@/lib/modules";
import { withAuth, getMe } from "@/lib/server-api";
import type { DashboardPeriod } from "@/lib/types";
import { DashboardView } from "./_dashboard/dashboard-view";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.dashboard.metaTitle") };
}

const PERIODS: DashboardPeriod[] = ["30d", "90d", "365d"];

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ period?: string; dashboard?: string }> }) {
  const sp = await searchParams;
  const period = PERIODS.find((p) => p === sp.period) ?? "30d";
  const { user, org } = await getMe();
  // The dashboard belongs to the pm module; without it the home is the first module page.
  if (!hasModule(org, "pm")) redirect(hasModule(org, "tms") ? "/app/projects" : "/app/settings");
  const [dashboard, data, all] = await withAuth(async (api) => {
    const def = await api.defaultDashboard();
    const list = await api.dashboards().then((r) => r.items).catch(() => [def]);
    const d = (sp.dashboard && list.find((x) => x.id === sp.dashboard)) || def;
    return [d, await api.dashboardData(d.id, period), list] as const;
  }, "/app");
  return (
    <DashboardView
      key={`${dashboard.id}-${dashboard.updated_at ?? ""}`}
      dashboard={dashboard}
      dashboards={all}
      data={data}
      period={period}
      canEdit={user.role === "pm"}
    />
  );
}
