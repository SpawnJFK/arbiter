import type { Metadata } from "next";
import { withAuth, getMe } from "@/lib/server-api";
import type { DashboardPeriod } from "@/lib/types";
import { DashboardView } from "./_dashboard/dashboard-view";

export const metadata: Metadata = { title: "Dashboard" };

const PERIODS: DashboardPeriod[] = ["30d", "90d", "365d"];

export default async function DashboardPage({ searchParams }: { searchParams: Promise<{ period?: string; dashboard?: string }> }) {
  const sp = await searchParams;
  const period = PERIODS.find((p) => p === sp.period) ?? "30d";
  const { user } = await getMe();
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
