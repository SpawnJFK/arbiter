import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import type { Account, Workflow } from "@/lib/types";
import { NewProjectWizard } from "./wizard";

export const metadata: Metadata = { title: "New project" };

export default async function NewProjectPage({ searchParams }: { searchParams: Promise<{ account?: string }> }) {
  const { account } = await searchParams;
  const { org, user } = await getMe();
  // CRM and workflow templates are PM-only.
  let accounts: Account[] = [];
  let workflows: Workflow[] = [];
  if (user.role === "pm") {
    [accounts, workflows] = await withAuth(
      async (api) => Promise.all([api.accounts({ limit: 200 }).then((r) => r.items), api.workflows({ limit: 200 }).then((r) => r.items)]),
      "/app/projects/new",
    );
  }
  return (
    <>
      <PageHeader
        title="New project"
        description="Upload a file, pick languages, then compare tiers before anything runs. You are not charged until you start the project."
      />
      <NewProjectWizard
        defaultTier={org?.default_tier ?? "hybrid"}
        regulated={org?.regulated ?? false}
        vertical={org?.vertical ?? null}
        accounts={accounts}
        workflows={workflows.filter((w) => w.available !== false)}
        initialAccountId={accounts.some((a) => a.id === account) ? account! : ""}
      />
    </>
  );
}
