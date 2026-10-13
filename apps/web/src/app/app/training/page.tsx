import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { EmptyState, PageHeader } from "@/components/ui/misc";
import { ApiError, type Api } from "@/lib/api";
import { withAuth } from "@/lib/server-api";
import { TrainingConsole } from "./training-console";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("training.page.title") };
}

async function load(api: Api) {
  try {
    return await Promise.all([api.org(), api.trainingJobs(), api.customModels(), api.engineCredentials()]);
  } catch (e) {
    // module "engine" disabled (404) or no permission to manage engines (403)
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) return null;
    throw e;
  }
}

export default async function TrainingPage() {
  const { t } = await getI18n();
  const data = await withAuth(load, "/app/training");
  if (!data) {
    return (
      <>
        <PageHeader title={t("training.page.title")} />
        <EmptyState title={t("engines.page.unavailable")} description={t("engines.page.unavailableDescription")} />
      </>
    );
  }
  const [org, jobs, models, keys] = data;
  return (
    <>
      <PageHeader title={t("training.page.title")} description={t("training.page.description")} />
      <TrainingConsole org={org} initialJobs={jobs.items} initialModels={models.items} keys={keys.items} />
    </>
  );
}
