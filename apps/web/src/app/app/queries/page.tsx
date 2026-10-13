import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { withAuth } from "@/lib/server-api";
import { QueriesInbox } from "./queries-inbox";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.queries.title") };
}

export default async function QueriesPage() {
  const { t } = await getI18n();
  const first = await withAuth((api) => api.openQueries({ limit: 50 }), "/app/queries");
  return (
    <>
      <PageHeader title={t("app.queries.title")} description={t("app.queries.description")} />
      <QueriesInbox initial={first.items} />
    </>
  );
}
