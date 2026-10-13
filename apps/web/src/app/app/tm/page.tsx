import { getI18n } from "@/lib/i18n/server";
import type { Metadata } from "next";
import { PageHeader } from "@/components/ui/misc";
import { getMe } from "@/lib/server-api";
import { TmTabs } from "./tm-tabs";

export async function generateMetadata(): Promise<Metadata> {
  const { t } = await getI18n();
  return { title: t("app.tm.translationMemory") };
}

export default async function TmPage() {
  const { t } = await getI18n();
  const { user } = await getMe();
  return (
    <>
      <PageHeader
        title={t("app.tm.translationMemory")}
        description={t("app.tm.approvedSegmentsAreStoredAutomatically")}
      />
      <TmTabs canEdit={user.role === "pm"} />
    </>
  );
}
