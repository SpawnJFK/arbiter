import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { getMe, withAuth } from "@/lib/server-api";
import type { Account, Workflow } from "@/lib/types";
import { NewProjectWizard } from "./wizard";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.projects.new.newProject") };
}

export default async function NewProjectPage({ searchParams }: { searchParams: Promise<{ account?: string }> }) {
  const { t } = await getI18n();
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
        title={t("app.projects.new.newProject")}
        description={t("app.projects.new.uploadAFilePickLanguages")}
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
