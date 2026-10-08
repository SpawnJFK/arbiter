import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { TaskList } from "./task-list";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.crm.tasks.myTasks") };
}

export default async function TasksPage() {
  const { t } = await getI18n();
  const [acts, accounts] = await withAuth((api) => Promise.all([api.activities({ open: true, limit: 200 }), api.accounts({ limit: 200 })]), "/app/crm/tasks");
  const names = Object.fromEntries(accounts.items.map((a) => [a.id, a.name]));
  return (
    <>
      <PageHeader title={t("app.crm.tasks.myTasks")} description={t("app.crm.tasks.openActivitiesAcrossAllAccounts")} />
      <TaskList initial={acts.items} accountNames={names} />
    </>
  );
}
