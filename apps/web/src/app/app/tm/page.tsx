import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { TmScreen } from "./tm-screen";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.tm.translationMemory") };
}

export default async function TmPage() {
  const { t } = await getI18n();
  return (
    <>
      <PageHeader
        title={t("app.tm.translationMemory")}
        description={t("app.tm.approvedSegmentsAreStoredAutomatically")}
      />
      <TmScreen />
    </>
  );
}
