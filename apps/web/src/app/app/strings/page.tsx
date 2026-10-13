import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { StringProjects } from "./projects-list";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.strings.title") };
}

export default async function StringsPage() {
  const { t } = await getI18n();
  return (
    <>
      <PageHeader title={t("app.strings.title")} description={t("app.strings.description")} />
      <StringProjects />
    </>
  );
}
