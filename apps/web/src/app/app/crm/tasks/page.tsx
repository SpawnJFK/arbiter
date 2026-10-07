import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { TaskList } from "./task-list";

export const metadata: Metadata = { title: "My tasks" };

export default async function TasksPage() {
  const [acts, accounts] = await withAuth((api) => Promise.all([api.activities({ open: true, limit: 200 }), api.accounts({ limit: 200 })]), "/app/crm/tasks");
  const names = Object.fromEntries(accounts.items.map((a) => [a.id, a.name]));
  return (
    <>
      <PageHeader title="My tasks" description="Open activities across all accounts, soonest due first." />
      <TaskList initial={acts.items} accountNames={names} />
    </>
  );
}
